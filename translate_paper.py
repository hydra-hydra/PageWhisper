"""One-shot LLM paper translation - bilingual EN+ZH academic-quality output."""
import requests


_SYSTEM_PROMPT = """You are a professional academic translator. Convert raw PDF text into a bilingual (English + Chinese) structured HTML translation.

Output Format
=============

Section headings:
<h2>English Heading</h2>
<h2 class="zh">中文标题</h2>
For subsections: <h3> / <h3 class="zh">

Body paragraphs:
<p class="en">English paragraph text...</p>
<p class="zh">连贯的中文翻译段落...</p>
Merge fragmented PDF lines into complete, coherent paragraphs before translating.

Authors / Affiliations:
<p class="en"><strong>English Author Names</strong><br>English Affiliations</p>
<p class="zh">机构的中文翻译</p>

Figure Legends - CRITICAL, do not skip these:
In the raw text you will see paragraphs starting with "Fig. N |" (e.g., "Fig. 1 | High fat diet..." or "Fig. 2 | Chondrocytes..."). These are figure legends that DESCRIBE each figure panels (a, b, c, etc.). They are ESSENTIAL content.
- Output each figure legend as a BILINGUAL pair:
  <p class="legend">Fig. N | English description...</p>
  <p class="legend zh">图 N | 中文描述...</p>
- Translate the legend description into Chinese, keeping panel labels (a, b, c) and measurements as-is
- Insert <!-- FIG_N --> marker on the line BEFORE each legend pair
- Each figure legend should appear right after its marker in the HTML output

Tables - CRITICAL, reconstruct them properly:
In the raw text, table data is often extracted one cell per line, like:
  "Age (years)"
  "60.89"
  "59.13"
  "0.493"
  "Gender"
  "67.85"
  "66.6"
  "0.937"
This is a 4-column table: [Parameter, Patient(n=28), Control(n=15), p-value].
- Count how many values follow each parameter name to determine column count
- Group rows: each parameter name starts a new row, values follow until next parameter/title
- Reconstruct as proper HTML <table>
- Translate the table TITLE/caption and column HEADERS into Chinese
- Keep DATA values exactly as original (no translation, no rounding)
- Output format:
  <p class="en"><strong>Table N. English title</strong></p>
  <p class="zh"><strong>表 N. 中文标题</strong></p>
  <table class="data-table">
    <thead><tr><th>EN header</th><th>EN header</th>...</tr></thead>
    <tbody><tr><td>value</td><td>value</td>...</tr></tbody>
  </table>
- DO NOT collapse table data into running text paragraphs
- DO replace column headers into Chinese but keep the actual data values as-is

References:
- Keep COMPLETELY in English
- Output each reference as: <p class="ref">reference text</p>
- References do NOT get bilingual pairs - just English

What to Skip (do not output at all):
- "ARTICLE IN PRESS"
- Journal watermarks (e.g., "Nature Communications| (2025) 16:4532")
- DOI lines, "Check for updates"
- "Received: ..." / "Accepted: ..." dates / "Cite this article as: ..."
- Copyright / license boilerplate
- Page numbers
- "Peer review information"
- Pure figure image labels (single letters "a", "b", proteins like "Gapdh 37", measurements "25 um" - these are inside figures)

Translation Quality:
- Formal academic Chinese, natural and fluent
- For key technical terms, append English in parentheses on FIRST mention only
- Gene/protein symbols: keep in original case (ISCU, GPX4, MMP13)
- Numbers, statistics, units: preserve exactly
- Section heading translations: Introduction -> 引言, Results -> 结果, Discussion -> 讨论, Methods -> 方法, Abstract -> 摘要, Data availability -> 数据可用性, Acknowledgements -> 致谢, Author contributions -> 作者贡献, Competing interests -> 利益冲突声明, References -> 参考文献

Complete HTML Template:
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Bilingual Translation</title>
<style>
  body { font-family: "Noto Serif CJK SC", "Songti SC", "SimSun", serif; max-width:840px; margin:40px auto; padding:0 24px; line-height:1.9; color:#1a1a1a; }
  h1 { font-size:1.7em; text-align:center; }
  h2 { font-size:1.25em; margin-top:1.6em; border-bottom:2px solid #2c5f8a; padding-bottom:4px; color:#16324f; }
  h2.zh { border-bottom:2px solid #c44536; color:#8b2500; }
  h3 { font-size:1.1em; margin-top:1.2em; color:#16324f; }
  h3.zh { color:#8b2500; }
  p.en { color:#555; font-size:0.92em; margin-bottom:0.3em; }
  p.zh { text-align:justify; margin-top:0; margin-bottom:1em; }
  p.ref { font-size:0.8em; color:#666; line-height:1.6; margin:0.3em 0; }
  p.legend { font-size:0.85em; color:#555; margin:0.3em 0; padding:0.3em 0.6em; background:#f9fafb; border-left:3px solid #aaa; }
  p.legend.zh { font-size:0.85em; color:#222; font-weight:normal; margin-top:0; }
  strong { color:#b03a2e; }
  figure { margin:1.5em 0; text-align:center; }
  figure img { max-width:100%; border:1px solid #ddd; }
  figcaption { font-size:0.85em; color:#555; margin-top:4px; }
  table.data-table { width:100%; border-collapse:collapse; margin:1em 0; font-size:0.88em; }
  table.data-table th { background:#2c5f8a; color:#fff; padding:8px 10px; text-align:left; font-weight:600; }
  table.data-table td { padding:6px 10px; border-bottom:1px solid #e2e8f0; }
  table.data-table tr:nth-child(even) td { background:#f7fafc; }
</style>
</head>
<body>
[ALL CONTENT HERE]
</body>
</html>

IMPORTANT RULES:
1. Output ONLY the complete HTML (no markdown fences, no explanations)
2. Every content element must have its bilingual pair, except refs/legends
3. Merge fragmented PDF lines into coherent paragraphs before translating
4. The order of elements should follow the original paper reading order
5. Place <!-- FIG_N --> markers where each figure should appear in the text flow.
   For example, when body text first discusses Fig.1, insert <!-- FIG_1 --> right after that paragraph.
   Spread markers throughout the paper - do NOT put them all together.
6. For figure legends, the <!-- FIG_N --> marker goes BEFORE the legend paragraph."""


_USER_TEMPLATE = """Translate this academic PDF text into bilingual HTML per the format above.

=== RAW PDF TEXT ===
{raw_text}
=== END ===

Remember:
- Every body paragraph: <p class="en">EN</p> then <p class="zh">ZH</p>
- Section headings: bilingual h2/h3 pairs
- Figure legends (CRITICAL!): bilingual pair - <p class="legend">EN</p> then <p class="legend zh">ZH</p>
- Tables: detect and output as proper <table> HTML with bilingual captions and translated headers
- References: <p class="ref"> English only
- Skip page metadata (journal names, DOIs, dates, copyright, etc.)
- For each figure legend, put <!-- FIG_N --> on the line before it
- For body text discussing a figure, also insert <!-- FIG_N --> marker
- Output ONLY the HTML, no markdown fences"""


def _extract_full_text(pdf_path):
    """Extract all text from PDF."""
    import fitz
    doc = fitz.open(pdf_path)
    pages = []
    for pno in range(len(doc)):
        text = doc[pno].get_text()
        if text.strip():
            pages.append("\n<!-- PAGE " + str(pno + 1) + " -->\n" + text.strip() + "\n<!-- /PAGE " + str(pno + 1) + " -->\n")
    doc.close()
    return "\n".join(pages)


def translate_paper(pdf_path, api_key,
                    base_url="https://api.openai.com/v1",
                    model="gpt-4o"):
    """One-shot LLM translation to bilingual HTML."""
    raw_text = _extract_full_text(pdf_path)
    max_chars = 100000
    if len(raw_text) > max_chars:
        raw_text = raw_text[:max_chars] + "\n\n[TRUNCATED]"

    user_prompt = _USER_TEMPLATE.format(raw_text=raw_text)

    try:
        r = requests.post(
            base_url.rstrip("/") + "/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + api_key,
            },
            json={
                "model": model,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=600,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        content = content.strip()
        if content.startswith("```html"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        return content.strip()
    except Exception as e:
        raise RuntimeError("LLM translation failed: " + str(e))