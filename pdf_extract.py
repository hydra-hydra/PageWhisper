"""Extract coherent paragraphs and figures from a PDF.

Uses get_text("dict") for font metadata to detect headings and merge fragments
into readable paragraphs. Skips page chrome (headers, footers, DOIs, dates, etc.).

Flow items:
  {"kind":"text", "text":..., "heading_level":0|1|2|3, "is_ref":bool, "translatable":bool}
  {"kind":"figure", "fig_no":int, "img":"figures/fig_N.png"}
"""
import os
import re
from statistics import mode as _mode
import fitz

# ── simple skip strings ───────────────────────────────────────────
_SKIP_STRINGS = {
    "ARTICLE IN PRESS",
    "Article in Press",
    "Article",
    "#These authors contributed equally",
    "*Corresponding author:",
}
_SKIP_EXACT_START = {
    "*Corresponding author",
    "Corresponding author",
}

# ── front-matter skip patterns ────────────────────────────────────
_FRONT_MATTER_RES = [
    # editorial notice (MyriadPro font text on page 1)
    re.compile(r"we\s+are\s+providing\s+an\s+unedited", re.I),
    re.compile(r"transparent\s+peer\s+review", re.I),
    re.compile(r"advance\s+online", re.I),
    re.compile(r"legal\s+disclaimers", re.I),
    # license footer
    re.compile(r"creative\s+commons", re.I),
    re.compile(r"open\s+access\s+this\s+article\s+is\s+licensed", re.I),
    re.compile(r"all\s+rights?\s+reserved", re.I),
    re.compile(r"non-commercial\s+use", re.I),
    re.compile(r"share\s+adapted\s+material", re.I),
    re.compile(r"article['\u2019]s\s+creative\s+commons\s+licen[cs]e", re.I),
    # editorial dates
    re.compile(r"^\s*(?:received|accepted|published\s+online)\s*:", re.I),
    re.compile(r"^\s*cite\s+this\s+article\s*", re.I),
]


def _is_skip_line(text: str, y_frac: float, font_name: str) -> bool:
    """Quick skip check per line before paragraph merging."""
    t = text.strip()
    if not t:
        return True

    # "ARTICLE IN PRESS" watermark
    if t in _SKIP_STRINGS:
        return True

    # Corresponding author metadata
    for s in _SKIP_EXACT_START:
        if t.startswith(s):
            return True

    # Editorial/MyriadPro font on first pages
    if "MyriadPro" in font_name:
        return True

    # Pure page number
    if re.fullmatch(r"[\d\s\-]+", t):
        return True

    # DOI / URL
    if re.match(r"^https?://|doi\.org", t, re.I):
        return True

    # Email address
    if re.match(r"^[\w\.\-]+@[\w\.\-]+$", t):
        return True

    # Email line
    if re.match(r"^\s*(?:e?-?mail|E-?mail)\s*:", t):
        return True

    # Affiliation line (starts with digit like "1Department of...")
    if re.match(r"^\d{1,2}[A-Z]", t):
        return True

    low = t.lower()
    for r in _FRONT_MATTER_RES:
        if r.search(low):
            return True

    # journal footer pattern: "Nature Communications| (2025) 16:4532"
    if re.search(r"nature\s+communications\s*[\|\]]?\s*\(?\s*\d{4}\s*\)?", low):
        return True
    # generic "(2025) 16:4532" or "(2025) NN:NNNN" volume/issue/page
    if re.search(r"\(\s*\d{4}\s*\)\s*\d+\s*:\s*\d+", low):
        return True
    # "Peer review information..." footer line
    if "peer review information" in low or "reprints and permissions" in low:
        return True
    # Open Access license footer (long, bottom of page)
    if y_frac > 0.85 and ("open access" in low or "creative commons" in low):
        return True

    # License footer (bottom 15% of page, small font, long)
    if y_frac > 0.85 and len(t) > 80:
        return True

    # Short all-caps (journal banner)
    if t.isupper() and len(t) < 45 and "(" not in t:
        return True

    # Standalone dates
    if re.fullmatch(r"\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}", t, re.I):
        return True

    return False


# ── line extraction from dict ──────────────────────────────────────
def _extract_lines(page: fitz.Page) -> list:
    """Return [{text, x0, y0, font_size, is_bold, font_name}, ...] sorted top→bottom."""
    d = page.get_text("dict")
    lines = []
    for block in d.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            text = "".join(s.get("text", "") for s in spans).strip()
            if not text:
                continue
            sizes = [s.get("size", 10) for s in spans]
            font_size = max(sizes) if sizes else 10
            fonts = [s.get("font", "") or "" for s in spans]
            is_bold = any(("Bold" in f) or f.endswith(".B") or f.endswith("-Bold")
                         or f.endswith("-BoldMT") for f in fonts)
            font_name = fonts[0] if fonts else ""
            bbox = list(line["bbox"])
            lines.append({
                "text": text,
                "x0": bbox[0], "y0": bbox[1],
                "font_size": font_size,
                "is_bold": is_bold,
                "font_name": font_name,
            })
    lines.sort(key=lambda L: (round(L["y0"] / 8), L["x0"]))
    return lines


# ── paragraph merging ──────────────────────────────────────────────
def _merge_paragraphs(lines: list, page_h: float, body_font: float = 10,
                    fig_regions: list = None) -> list:
    """Merge raw lines into paragraphs with heading levels.

    Returns [{text, heading_level, font_size}, ...].
    """
    if not lines:
        return []

    paragraphs = []
    buf = ""
    buf_level = 0
    buf_font = 0
    last_heading_text = ""   # track previous heading for merge
    in_fig_captions = False   # track figure caption zone

    def _flush():
        nonlocal buf, buf_level, buf_font
        if buf.strip():
            paragraphs.append({
                "text": buf.strip(),
                "heading_level": buf_level,
                "font_size": buf_font,
            })
        buf = ""
        buf_level = 0
        buf_font = 0

    for L in lines:
        text = L["text"]
        fs = L["font_size"]
        bold = L["is_bold"]
        font_name = L["font_name"]
        y_frac = L["y0"] / page_h if page_h else 0.5

        if _is_skip_line(text, y_frac, font_name):
            _flush()
            continue

        # Skip text inside figure regions (image labels)
        if fig_regions and any(
            L["x0"] >= r[0] - 15 and L["x0"] <= r[2] + 15 and
            L["y0"] >= r[1] - 15 and L["y0"] <= r[3] + 15
            for r in fig_regions
        ):
            _flush()
            continue

        # Detect figure caption zone: "Fig.N" or bold continuation lines
        is_fig_caption = bool(re.match(r"^fig\.?\s*\d+", text, re.I))
        is_fig_continuation = bool(re.search(r"\(scale\s+bar|\(n\s*=|biorender|created with", text, re.I))
        if is_fig_caption:
            in_fig_captions = True
        elif not bold:
            in_fig_captions = False

        # In figure captions zone, treat all bold as body (not heading)
        if in_fig_captions and is_fig_continuation:
            is_heading = False
        else:
            is_heading = (bold and fs >= 9 and len(text) < 250 and len(text) > 2
                          and not is_fig_caption and not is_fig_continuation)

        if in_fig_captions and bold and not is_fig_caption:
            # Bold continuation in figure caption → body text
            is_heading = False
        if is_heading:
            # Merge with LAST FLUSHED heading ONLY if:
            # - prev heading is long (≥40 chars, likely a title) and doesn't end with punctuation
            # - current heading is very short (<20 chars, clearly a continuation fragment)
            should_merge = (
                last_heading_text
                and not last_heading_text.endswith((".", "?", "!"))
                and len(last_heading_text) >= 40
                and len(text) < 20
            )
            if should_merge:
                if paragraphs and paragraphs[-1]["heading_level"] > 0:
                    prev = paragraphs[-1]
                    if prev["text"].rstrip().endswith("-"):
                        prev["text"] = prev["text"].rstrip()[:-1] + text
                    else:
                        prev["text"] = prev["text"].rstrip() + " " + text
                    if prev["heading_level"] == 3 and len(prev["text"]) > 40:
                        prev["heading_level"] = 2
                    last_heading_text = prev["text"]
                    continue
            level = 1 if fs >= body_font * 1.15 or fs >= 13 else (2 if len(text) > 35 else 3)
            _flush()
            buf = text
            buf_level = level
            buf_font = fs
            _flush()
            last_heading_text = text
            continue

        last_heading_text = ""   # reset when we hit body text

        # Body text paragraph merging
        if not buf:
            buf = text
            buf_level = 0
            buf_font = fs
            continue

        # Merge if: previous doesn't end with sentence-ending punctuation,
        # or this line starts lowercase (continuation)
        buf_ends = buf.rstrip().endswith((".", "?", "!"))
        is_continuation = text and text[0].islower()

        if not buf_ends or is_continuation:
            if buf.rstrip().endswith("-"):
                buf = buf.rstrip()[:-1] + text   # de-hyphenate
            else:
                buf = buf.rstrip() + " " + text
        else:
            _flush()
            buf = text
            buf_level = 0
            buf_font = fs

    _flush()
    return paragraphs


# ── figure extraction ──────────────────────────────────────────────
def _extract_figures(doc: fitz.Document, figdir: str) -> list:
    """Return [{fig_no, page, img}, ...] for embedded images."""
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


# ── main extract ───────────────────────────────────────────────────
def extract_document(pdf_path: str, figdir: str, translate_refs: bool = False) -> dict:
    """Extract flow (coherent paragraphs + figure anchors) and metadata.

    Returns:
        {"flow": [...], "title": str, "stats": {...}}
    """
    doc = fitz.open(pdf_path)
    n_pages = len(doc)

    # ── first pass: find dominant body font size ──
    all_sizes = []
    for pno in range(1, n_pages):   # skip page 0 (metadata)
        for L in _extract_lines(doc[pno]):
            yf = L["y0"] / doc[pno].rect.height
            if 0.15 < yf < 0.85 and not L["is_bold"]:   # body zone, non-bold
                all_sizes.append(L["font_size"])
    if not all_sizes:
        all_sizes = [10]
    try:
        body_font = _mode(round(s, 1) for s in all_sizes)
    except Exception:
        body_font = sorted(all_sizes)[len(all_sizes)//2]

    # ── extract paragraphs from pages ──
    text_items = []
    in_refs = False
    in_front_matter = True   # True until we find real body content

    # Non-translatable back-matter sections (before References)
    _NON_BODY_SECTIONS = {
        "data availability", "acknowledgements", "acknowledgments",
        "author contributions", "competing interests",
    }
    # Known section start headings
    _SECTION_STARTS = {"abstract", "introduction", "background", "summary"}

    for pno in range(n_pages):
        # Page 0 is always metadata (journal banner, DOI, dates)
        if pno == 0:
            continue

        page = doc[pno]
        lines = _extract_lines(page)

        # Build figure regions for this page (to filter text inside figures)
        page_fig_regions = []
        try:
            for info in page.get_image_info():
                bbox = info.get("bbox")
                if not bbox: continue
                x0, y0, x1, y1 = bbox
                if (x1-x0) < 60 or (y1-y0) < 60: continue
                page_fig_regions.append(bbox)
        except Exception:
            pass

        paras = _merge_paragraphs(lines, page.rect.height, body_font, page_fig_regions)

        for p in paras:
            low = p["text"].lower().strip()

            # Exit front matter when we see a known section heading or real body content
            if in_front_matter:
                is_section_start = (
                    p["heading_level"] >= 1
                    and (low in _SECTION_STARTS or (len(p["text"]) > 30 and low.startswith("intro")))
                )
                if is_section_start:
                    in_front_matter = False
                else:
                    # Heuristic fallback: long non-affiliation text = body content
                    is_body = (
                        p["heading_level"] == 0 and len(p["text"]) > 80
                        and not re.match(r"^\d{1,2}[A-Z\u00c0-\u02af]", p["text"])
                        and not re.search(r"@|corresponding|contributed equally", p["text"], re.I)
                    )
                    if is_body:
                        in_front_matter = False
                    else:
                        continue   # skip front matter

            # Detect "References" heading
            if low == "references" and p["heading_level"] >= 1:
                in_refs = True
                text_items.append({
                    "text": p["text"], "heading_level": p["heading_level"],
                    "is_ref": False, "translatable": True,
                })
                continue

            # Non-body sections: keep original, don't translate
            is_non_body = low in _NON_BODY_SECTIONS and p["heading_level"] >= 1

            text_items.append({
                "text": p["text"],
                "heading_level": p["heading_level"],
                "is_ref": in_refs,
                "translatable": not (in_refs or is_non_body) or translate_refs,
            })

    # ── figures ──
    images = _extract_figures(doc, figdir)

    # ── extract figure captions from text items ──
    # Pattern: "Fig. N | description..." (with pipe)
    # This catches both legend sections and captions interleaved with body
    fig_captions = {}
    cleaned_text_items = []

    for it in text_items:
        t = it["text"]
        m = re.match(r"^fig\.?\s*(\d+)\s*\|", t, re.I)
        if m:
            fig_no = int(m.group(1))
            caption = t[m.end():].strip()
            if caption and fig_no not in fig_captions:
                fig_captions[fig_no] = caption
                continue   # remove from text flow
        cleaned_text_items.append(it)
    text_items = cleaned_text_items

    # ── insert figure anchors at first citation, attach caption ──
    flow = []
    placed = set()
    for it in text_items:
        for img in images:
            if img["fig_no"] in placed:
                continue
            if re.search(rf"fig\.?\s*{img['fig_no']}\b", it["text"], re.I):
                fig_item = {
                    "kind": "figure", "fig_no": img["fig_no"], "img": img["img"],
                    "caption": fig_captions.get(img["fig_no"], ""),
                }
                flow.append(fig_item)
                placed.add(img["fig_no"])
        flow.append({"kind": "text", **it})

    for img in images:
        if img["fig_no"] not in placed:
            flow.append({
                "kind": "figure", "fig_no": img["fig_no"], "img": img["img"],
                "caption": fig_captions.get(img["fig_no"], ""),
            })
            placed.add(img["fig_no"])

    # ── title: extract from page 0 (metadata page) by largest bold text ──
    title = ""
    try:
        # Try page 0 first, then page 1
        for title_page_idx in [0, 1]:
            tp = doc[title_page_idx]
            tp_lines = _extract_lines(tp)
            bold_lines = [L for L in tp_lines if L["is_bold"] and L["font_size"] >= 10
                          and len(L["text"]) > 20]
            bold_lines.sort(key=lambda L: -L["font_size"])
            if bold_lines:
                title_parts = []
                for L in bold_lines:
                    if not title_parts:
                        title_parts.append(L["text"])
                    elif abs(L["font_size"] - bold_lines[0]["font_size"]) < 3:
                        title_parts.append(L["text"])
                    else:
                        break
                title = " ".join(title_parts)
                break
    except Exception:
        pass
    if not title:
        for it in text_items:
            if it["heading_level"] >= 1 and len(it["text"]) > 20:
                title = it["text"]
                break

    stats = {
        "pages": n_pages,
        "text_blocks": sum(1 for f in flow if f["kind"] == "text"),
        "figures": len(images),
    }
    doc.close()
    return {"flow": flow, "title": title, "stats": stats}
