"""LLM-powered smart PDF content extraction.

Strategy:
1. Use pdf_extract._extract_lines for clean line-level extraction with font info
2. Group only visually-contiguous lines into paragraphs (respect page boundaries, gaps, font changes)
3. Filter out image labels (very short text near figures, common patterns like "a", "b", "n=")
4. Send clean paragraphs to LLM for classification
5. LLM decides: body / heading / figure_caption / reference / skip

This works across ALL journal layouts without pattern tweaking.
"""
import json
import os
import re
import fitz
import requests

import pdf_extract

# Image-label patterns to ALWAYS filter out before sending to LLM
_LABEL_PATTERNS = [
    re.compile(r"^\s*[a-z]\s*$", re.I),                # single letter "a"
    re.compile(r"^\s*\d+\s*(mm|μ|um|nm|cm|m|kb|mg|ml|s|h|min|sec|hr|day|wk|yr)\s*$", re.I),
    re.compile(r"^\s*\d+\s*:\s*\d+\s*$"),              # "5:10"
    re.compile(r"^\s*scale\s+bar", re.I),
    re.compile(r"^\s*\(?\s*n\s*=\s*\d+", re.I),
    re.compile(r"^\s*sham\s*$", re.I),
    re.compile(r"^\s*control\s*$", re.I),
    re.compile(r"^\s*p\s*[<>=]\s*0?\.", re.I),
    re.compile(r"^\s*[a-z0-9-]{1,4}$", re.I),           # very short codes
    re.compile(r"^\s*[α-ωΑ-Ω]\s*$"),                  # Greek single letter
]

# Common protein/gene names that look like labels but should be preserved
_PROTEIN_PATTERNS = re.compile(r"^[A-Z][A-Z0-9]{2,8}$")  # GAPDH, MMP13, etc.


def _is_image_label(text: str) -> bool:
    t = text.strip()
    if len(t) > 8:
        return False
    for pat in _LABEL_PATTERNS:
        if pat.match(t):
            return True
    return False


def _clean_paragraphs_from_lines(lines: list, page_h: float) -> list:
    """Group visually-contiguous lines into paragraphs.

    Rules:
    - Lines with vertical gap > 5pt → new paragraph
    - Font size change > 2pt → new paragraph
    - Lines that look like image labels → skip
    - All lines on same page
    """
    if not lines:
        return []

    paragraphs = []
    buf = ""
    buf_font = 0
    last_y1 = 0

    def _flush():
        nonlocal buf, buf_font
        if buf.strip():
            paragraphs.append({"text": buf.strip(), "font_size": buf_font})
        buf = ""
        buf_font = 0

    for L in lines:
        text = L["text"]
        fs = L["font_size"]

        # Skip image labels
        if _is_image_label(text):
            _flush()
            continue

        # Skip very short non-label text
        if len(text) < 4 and not _PROTEIN_PATTERNS.match(text):
            _flush()
            continue

        # Skip pure numeric/symbol strings
        if re.match(r"^[\d\s.,:;\-\(\)\[\]/\\]+$", text):
            _flush()
            continue

        # New paragraph if gap > 2x font_size (lines too far apart) or font size change > 2pt
        gap = L["y0"] - last_y1
        font_diff = abs(fs - buf_font) if buf else 0

        # Threshold: gap should be smaller than 1.8× font_size to be same paragraph
        gap_threshold = max(buf_font, fs) * 1.8 if buf else 100

        if buf and (gap > gap_threshold or font_diff > 2):
            _flush()

        if not buf:
            buf_font = fs

        if buf and buf.rstrip().endswith("-"):
            buf = buf.rstrip()[:-1] + text
        else:
            buf = (buf + " " + text).strip() if buf else text

        last_y1 = L["y0"]

    _flush()
    return paragraphs


def _extract_figures(doc: fitz.Document, figdir: str) -> list:
    images = []
    seen = set()
    fig_no = 0
    for pno in range(len(doc)):
        page = doc[pno]
        try:
            infos = page.get_image_info()
        except Exception:
            infos = []
        for info in infos:
            bbox = info.get("bbox")
            if not bbox:
                continue
            x0, y0, x1, y1 = bbox
            w, h = x1 - x0, y1 - y0
            if w < 60 or h < 60:
                continue
            key = (pno, round(x0), round(y0), round(x1), round(y1))
            if key in seen:
                continue
            seen.add(key)
            fig_no += 1
            try:
                clip = fitz.Rect(x0, y0, x1, y1)
                pix = page.get_pixmap(clip=clip, matrix=fitz.Matrix(2, 2))
                fn = f"fig_{fig_no}.png"
                pix.save(os.path.join(figdir, fn))
                images.append({"fig_no": fig_no, "page": pno + 1, "img": "figures/" + fn})
            except Exception:
                fig_no -= 1
    return images


_CLASSIFY_PROMPT = """You are classifying paragraphs from an academic PDF into structural categories.

Categories:
- "body": real scientific content (introduction, results, discussion, methods paragraphs)
- "heading": section or subsection title (e.g., "Abstract", "Results", "Methods", "Introduction")
- "figure_caption": a figure legend paragraph that describes a specific figure's panels (often starts with "Fig. N")
- "reference": bibliographic reference entry
- "skip": page headers, footers, DOIs, watermarks, author names with affiliation numbers, affiliations, dates, copyright, journal name banners, page numbers, "Received/Accepted" lines, "Check for updates", random numbers/symbols, license notices, figure labels

Critical rules:
1. "ARTICLE IN PRESS", "Nature Communications|  (2025) 16:4532" → skip
2. "(2025) 16:4532" alone → skip
3. Author lines like "Chen Zhao1,4, Keyu Kong..." → skip
4. "1Department of Orthopedics, ..." → skip
5. "Received: 23 January 2024" → skip
6. Body text mentioning "(Fig. 3) IF experiments..." stays as "body"
7. "Fig. 3 | Concomitant cellular ferroptosis..." (long description with panel labels) → "figure_caption"
8. "Fig.3 ... title. a ... b ..." (description starts with title and includes panel details) → "figure_caption"
9. Bibliography entry with author + journal name + volume + pages → "reference"
10. "References", "Data availability", "Acknowledgements" → "heading"

IMPORTANT: Be strict about "skip". When in doubt between "body" and "skip" for short fragments, prefer "skip".

Return JSON: {"segments": [{"index":N,"type":"body","level":1}, ...]}
Include "level" only for "heading" (1=major section, 2=subsection, 3=sub-subsection)."""


def _classify_segments(segments: list, api_key: str, base_url: str,
                        model: str) -> list:
    """Call LLM to classify paragraphs."""
    if not segments:
        return []

    payload = [{"index": i, "text": seg["text"][:1200]}  # truncate to save tokens
               for i, seg in enumerate(segments)]

    chunk_size = 60
    results = []
    for chunk_start in range(0, len(payload), chunk_size):
        chunk = payload[chunk_start:chunk_start + chunk_size]
        user_msg = "Classify these segments:\n" + json.dumps(chunk, ensure_ascii=False)

        try:
            r = requests.post(
                base_url.rstrip("/") + "/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                json={
                    "model": model,
                    "temperature": 0.0,
                    "messages": [
                        {"role": "system", "content": _CLASSIFY_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    "response_format": {"type": "json_object"},
                },
                timeout=180,
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            resp = json.loads(content)
            for s in resp.get("segments", []):
                s["index"] = s["index"] + chunk_start
                results.append(s)
        except Exception as e:
            for i in range(chunk_start, min(chunk_start + chunk_size, len(segments))):
                results.append({"index": i, "type": "body"})

    results.sort(key=lambda x: x["index"])
    return results


def _extract_fig_no(text: str) -> int | None:
    m = re.match(r"fig\.?\s*(\d+)", text, re.I)
    return int(m.group(1)) if m else None


def smart_extract(pdf_path: str, figdir: str, api_key: str,
                  base_url: str = "https://api.openai.com/v1",
                  model: str = "gpt-4o-mini",
                  translate_refs: bool = False) -> dict:
    """Intelligently extract document structure using LLM classification."""
    doc = fitz.open(pdf_path)
    n_pages = len(doc)

    # Pre-compute figure regions per page (to filter text inside figures)
    fig_regions_per_page = {}
    for pno in range(n_pages):
        page = doc[pno]
        try:
            regions = []
            for info in page.get_image_info():
                bbox = info.get("bbox")
                if not bbox: continue
                x0, y0, x1, y1 = bbox
                if (x1-x0) < 60 or (y1-y0) < 60: continue
                regions.append(bbox)
            fig_regions_per_page[pno] = regions
        except Exception:
            fig_regions_per_page[pno] = []

    # Step 1: extract clean line-level data per page
    all_paras = []
    index = 0
    for pno in range(n_pages):
        page = doc[pno]
        lines = pdf_extract._extract_lines(page)
        page_h = page.rect.height
        fig_regions = fig_regions_per_page.get(pno, [])

        filtered = []
        for L in lines:
            yf = L["y0"] / page_h
            # Skip page chrome (top/bottom)
            if yf < 0.05 or yf > 0.92:
                continue
            # Skip text inside figure regions (image labels)
            if any(
                L["x0"] >= r[0] - 15 and L["x0"] <= r[2] + 15 and
                L["y0"] >= r[1] - 15 and L["y0"] <= r[3] + 15
                for r in fig_regions
            ):
                continue
            filtered.append(L)

        paras = _clean_paragraphs_from_lines(filtered, page_h)
        for p in paras:
            all_paras.append({"index": index, "text": p["text"], "page": pno})
            index += 1

    # Step 2: classify via LLM
    classifications = _classify_segments(all_paras, api_key, base_url, model)

    type_map = {}
    for c in classifications:
        type_map[c["index"]] = c

    # Step 3: extract figures
    images = _extract_figures(doc, figdir)

    # Step 4: extract figure captions
    fig_captions = {}
    for p in all_paras:
        c = type_map.get(p["index"], {})
        if c.get("type") == "figure_caption":
            fn = _extract_fig_no(p["text"])
            if fn and fn not in fig_captions:
                fig_captions[fn] = p["text"]

    # Step 5: build flow
    flow = []
    placed_figs = set()
    in_refs = False
    title = ""

    for p in all_paras:
        c = type_map.get(p["index"], {"type": "body"})
        seg_type = c.get("type", "body")
        text = p["text"]

        if seg_type == "skip":
            continue
        if seg_type == "figure_caption":
            continue

        # Try to use as title
        if not title and seg_type == "heading" and c.get("level") == 1 and len(text) > 20:
            title = text

        if seg_type == "heading":
            low = text.lower().strip()
            if low == "references":
                in_refs = True
            non_body = low in (
                "data availability", "acknowledgements", "acknowledgments",
                "author contributions", "competing interests",
            )
            flow.append({
                "kind": "text", "text": text,
                "heading_level": c.get("level", 2),
                "is_ref": False,
                "translatable": not non_body,
            })
            continue

        if seg_type == "reference":
            flow.append({
                "kind": "text", "text": text,
                "heading_level": 0, "is_ref": True,
                "translatable": translate_refs,
            })
            continue

        # body
        flow.append({
            "kind": "text", "text": text,
            "heading_level": 0, "is_ref": in_refs,
            "translatable": not in_refs or translate_refs,
        })

    # Step 6: insert figures at first body citation
    final_flow = []
    for it in flow:
        if it["kind"] == "text":
            for img in images:
                if img["fig_no"] in placed_figs:
                    continue
                if re.search(rf"fig\.?\s*{img['fig_no']}\b", it["text"], re.I):
                    final_flow.append({
                        "kind": "figure", "fig_no": img["fig_no"],
                        "img": img["img"],
                        "caption": fig_captions.get(img["fig_no"], ""),
                    })
                    placed_figs.add(img["fig_no"])
        final_flow.append(it)

    for img in images:
        if img["fig_no"] not in placed_figs:
            final_flow.append({
                "kind": "figure", "fig_no": img["fig_no"],
                "img": img["img"],
                "caption": fig_captions.get(img["fig_no"], ""),
            })

    # Fallback title
    if not title:
        for it in flow:
            if it["kind"] == "text" and it.get("heading_level", 0) >= 1 and len(it["text"]) > 15:
                title = it["text"]
                break
    if not title:
        # Use largest text on page 0
        try:
            p0_lines = pdf_extract._extract_lines(doc[0])
            big_bold = [L for L in p0_lines if L["is_bold"] and L["font_size"] >= 14]
            if big_bold:
                big_bold.sort(key=lambda L: -L["font_size"])
                title_parts = [big_bold[0]["text"]]
                for L in big_bold[1:]:
                    if abs(L["font_size"] - big_bold[0]["font_size"]) < 3:
                        title_parts.append(L["text"])
                    else:
                        break
                title = " ".join(title_parts)
        except Exception:
            pass

    stats = {
        "pages": n_pages,
        "text_blocks": sum(1 for f in final_flow if f["kind"] == "text"),
        "figures": len(images),
    }
    doc.close()
    return {"flow": final_flow, "title": title, "stats": stats}