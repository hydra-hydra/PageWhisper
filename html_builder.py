"""Build re-typeset bilingual HTML and PDF from extracted flow + translations.

Supports:
- keep_original: True=en+zh pairs, False=zh only
- h1/h2/h3 heading hierarchy from extracted heading_level
- Paper-like layout (max-width, justified body, proper line-height)
"""
import html as _html
import os


def _esc(s: str) -> str:
    return _html.escape(s, quote=False)


def _heading_tag(level: int) -> str:
    """Map heading_level (0-3) to HTML tag name."""
    return {1: "h1", 2: "h2", 3: "h3"}.get(level, None)


def build_html(doc: dict, tmap: dict, title: str = "", keep_original: bool = True) -> str:
    """Build re-typeset HTML from extracted document flow.

    doc: extract_document() result
    tmap: {english_text: chinese_text}
    title: document title
    keep_original: if True, show EN + ZH side by side; if False, ZH only
    """
    parts = []
    parts.append('<article class="doc">')

    if title:
        parts.append(f'<h1 class="doc-title">{_esc(title)}</h1>')
        parts.append('<p class="subtitle">')
        parts.append("英文原文（灰）与中文翻译（黑）对照 · 图片按原文相对位置嵌入"
                      if keep_original else
                      "中文翻译 · 图片按原文相对位置嵌入")
        parts.append('</p>')

    for it in doc["flow"]:
        if it["kind"] == "figure":
            cap_zh = tmap.get(it.get("caption", ""), "") if it.get("caption") else ""
            caption_html = ""
            if it.get("caption"):
                caption_html = f'<div class="fig-caption">'
                if keep_original:
                    caption_html += f'<p class="orig">{_esc(it["caption"])}</p>'
                if cap_zh:
                    caption_html += f'<p class="zh">{_esc(cap_zh)}</p>'
                elif not keep_original:
                    caption_html += f'<p class="zh">{_esc(it["caption"])}</p>'
                caption_html += '</div>'
            parts.append(
                f'<figure class="fig"><img src="{_esc(it["img"])}" alt="Fig {it["fig_no"]}"/>'
                f'<figcaption>图 {it["fig_no"]}（Fig. {it["fig_no"]}）</figcaption>'
                f'{caption_html}</figure>'
            )
            continue

        en = it["text"]
        zh = tmap.get(en, "")
        heading_level = it.get("heading_level", 0)
        is_ref = it.get("is_ref", False)

        # References and non-translatable: just show original
        if is_ref or not it.get("translatable", True):
            parts.append(f'<div class="pair ref"><p class="orig">{_esc(en)}</p></div>')
            continue

        tag = _heading_tag(heading_level)

        if tag:
            # Section/subsection heading
            if keep_original:
                parts.append(f'<div class="pair heading-pair">'
                             f'<{tag} class="orig-heading">{_esc(en)}</{tag}>'
                             f'<{tag} class="zh-heading">{_esc(zh) if zh else ""}</{tag}>'
                             f'</div>')
            else:
                parts.append(f'<{tag} class="zh-heading">{_esc(zh) if zh else _esc(en)}</{tag}>')
        else:
            # Body paragraph
            if keep_original:
                parts.append(f'<div class="pair">'
                             f'<p class="orig">{_esc(en)}</p>'
                             f'<p class="zh">{_esc(zh) if zh else ""}</p>'
                             f'</div>')
            else:
                if zh:
                    parts.append(f'<p class="zh">{_esc(zh)}</p>')
                else:
                    parts.append(f'<p class="orig">{_esc(en)}</p>')

    parts.append("</article>")

    css = """
:root{--zh:#111;--en:#777;--line:1.9;}
*{box-sizing:border-box;}
body{margin:0;background:#fff;color:var(--zh);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;}
.doc{max-width:840px;margin:34px auto;padding:0 26px;line-height:var(--line);}

/* title */
.doc-title{font-size:23px;line-height:1.45;margin:0 0 8px;font-weight:700;text-align:center;}
.subtitle{color:#999;font-size:13px;margin:0 0 22px;border-bottom:1px solid #eee;padding-bottom:12px;text-align:center;}

/* heading styles */
h1.orig-heading,h1.zh-heading{font-size:20px;line-height:1.5;margin:28px 0 12px;}
h2.orig-heading,h2.zh-heading{font-size:17px;line-height:1.5;margin:22px 0 8px;}
h3.orig-heading,h3.zh-heading{font-size:15px;line-height:1.5;margin:18px 0 6px;}
.orig-heading{color:var(--en);font-weight:600;}
.zh-heading{color:var(--zh);font-weight:700;}

/* body paragraph pair */
.pair{margin:0 0 13px;}
.orig{margin:0 0 3px;color:var(--en);font-size:14.5px;}
.zh{margin:0;color:var(--zh);font-size:16px;}

/* references */
.ref .orig{font-size:13px;color:#555;line-height:1.6;}
.ref{margin:4px 0;}

/* figures */
.fig{margin:24px 0;text-align:center;page-break-inside:avoid;}
.fig img{max-width:100%;border:1px solid #eee;border-radius:4px;}
.fig figcaption{margin-top:8px;color:#666;font-size:13px;}
.fig-caption{margin-top:10px;padding:10px 12px;background:#fafbfc;
  border-left:3px solid var(--brand);border-radius:4px;text-align:left;}
.fig-caption .orig{margin:0 0 4px;color:#777;font-size:13.5px;line-height:1.7;}
.fig-caption .zh{margin:0;color:#222;font-size:14px;line-height:1.8;}

@media print{
  .doc{margin:0;max-width:none;}
  @page{margin:16mm;}
  .fig,.pair{page-break-inside:avoid;}
}
"""
    html = f'<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
    html += f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    html += f'<title>{_esc(title) if title else "中英对照翻译"}</title>\n'
    html += f'<style>{css}</style>\n</head>\n<body>\n'
    html += "\n".join(parts) + "\n</body>\n</html>"
    return html


# ── PDF generation (reportlab) ─────────────────────────────────────
def _esc_rl(s: str) -> str:
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = s.replace("\n", "<br/>")
    return s


def build_pdf(doc: dict, tmap: dict, pdf_path: str,
              figures_base: str = "", keep_original: bool = True) -> str:
    """Build PDF from flow + translations using reportlab.

    Parameters:
      doc: extract_document() result
      tmap: {english_text: chinese_text}
      pdf_path: output path
      figures_base: base directory for figure image paths
      keep_original: include English original alongside Chinese
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Image, KeepTogether)
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from PIL import Image as PILImage

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    FONT = "STSong-Light"

    tmpl = SimpleDocTemplate(
        pdf_path, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=(doc.get("title") or "")[:80],
    )
    avail_w = tmpl.width
    avail_h = tmpl.height - 30

    styles = {
        "title": ParagraphStyle("tt", fontName=FONT, fontSize=16, leading=22,
                                spaceAfter=6, alignment=1),
        "h1_orig": ParagraphStyle("h1o", fontName=FONT, fontSize=14, leading=19,
                                  textColor=colors.HexColor("#555"), spaceAfter=2),
        "h1_zh": ParagraphStyle("h1z", fontName=FONT, fontSize=14, leading=19,
                                textColor=colors.HexColor("#111"), spaceAfter=8),
        "h2_orig": ParagraphStyle("h2o", fontName=FONT, fontSize=12.5, leading=17,
                                  textColor=colors.HexColor("#555"), spaceAfter=2),
        "h2_zh": ParagraphStyle("h2z", fontName=FONT, fontSize=12.5, leading=17,
                                textColor=colors.HexColor("#111"), spaceAfter=6),
        "h3_orig": ParagraphStyle("h3o", fontName=FONT, fontSize=11, leading=15,
                                  textColor=colors.HexColor("#555"), spaceAfter=1),
        "h3_zh": ParagraphStyle("h3z", fontName=FONT, fontSize=11, leading=15,
                                textColor=colors.HexColor("#111"), spaceAfter=5),
        "orig": ParagraphStyle("oo", fontName=FONT, fontSize=9.5, leading=14,
                               textColor=colors.HexColor("#666"), spaceAfter=2),
        "zh": ParagraphStyle("zz", fontName=FONT, fontSize=11, leading=17,
                             textColor=colors.HexColor("#111"), spaceAfter=8),
        "ref": ParagraphStyle("rr", fontName=FONT, fontSize=8, leading=11,
                              textColor=colors.HexColor("#555"), spaceAfter=4),
        "cap": ParagraphStyle("cc", fontName=FONT, fontSize=9, leading=12,
                              textColor=colors.HexColor("#666"),
                              alignment=1, spaceBefore=4, spaceAfter=10),
        "fig_cap_en": ParagraphStyle("fce", fontName=FONT, fontSize=8.5, leading=12,
                                     textColor=colors.HexColor("#555"),
                                     spaceBefore=2, spaceAfter=2),
        "fig_cap_zh": ParagraphStyle("fcz", fontName=FONT, fontSize=10, leading=14,
                                     textColor=colors.HexColor("#111"),
                                     spaceBefore=2, spaceAfter=10),
    }

    def _heading_style(level: int, variant: str) -> ParagraphStyle:
        key = f"h{level}_{variant}"
        return styles.get(key, styles["orig"])

    story = []
    if doc.get("title"):
        story.append(Paragraph(_esc_rl(doc["title"]), styles["title"]))
        story.append(Spacer(1, 6))

    for it in doc["flow"]:
        if it["kind"] == "figure":
            fp = it["img"]
            if figures_base and not os.path.isabs(fp):
                fp = os.path.join(figures_base, fp)
            try:
                iw, ih = PILImage.open(fp).size
                ratio = min(avail_w / iw, avail_h / ih, 2.0)
                dw, dh = iw * ratio, ih * ratio
                img = Image(fp, width=dw, height=dh)
                cap = Paragraph(f"图 {it['fig_no']}（Fig. {it['fig_no']}）",
                                styles["cap"])
                block = [img, cap]
                if it.get("caption"):
                    cap_en = it["caption"]
                    cap_zh = tmap.get(cap_en, "") if keep_original or not cap_en else ""
                    block.append(Spacer(1, 4))
                    block.append(Paragraph(_esc_rl(cap_en), styles["fig_cap_en"]))
                    if cap_zh:
                        block.append(Paragraph(_esc_rl(cap_zh), styles["fig_cap_zh"]))
                story.append(KeepTogether(block))
            except Exception:
                pass
            continue

        en = it["text"]
        zh = tmap.get(en, "")
        heading_level = it.get("heading_level", 0)
        is_ref = it.get("is_ref", False)

        if is_ref or not it.get("translatable", True):
            story.append(Paragraph(_esc_rl(en), styles["ref"]))
            continue

        if heading_level > 0:
            if keep_original:
                story.append(Paragraph(_esc_rl(en), _heading_style(heading_level, "orig")))
                if zh:
                    story.append(Paragraph(_esc_rl(zh), _heading_style(heading_level, "zh")))
                else:
                    story.append(Spacer(1, 4))
            else:
                story.append(Paragraph(_esc_rl(zh) if zh else _esc_rl(en),
                                       _heading_style(heading_level, "zh")))
            continue

        # Body paragraph
        if keep_original:
            story.append(Paragraph(_esc_rl(en), styles["orig"]))
            if zh:
                story.append(Paragraph(_esc_rl(zh), styles["zh"]))
        else:
            story.append(Paragraph(_esc_rl(zh) if zh else _esc_rl(en), styles["zh"]))

    tmpl.build(story)
    return pdf_path
