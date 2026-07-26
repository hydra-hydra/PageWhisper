"""PDF -> re-typeset bilingual HTML + PDF translator web service.

Endpoints:
  GET  /                        -> web UI
  POST /api/translate          -> start translation job {job_id}
  GET  /api/status/{job_id}    -> poll progress {stage, percent, elapsed, token_info, ...}
  GET  /api/download/{job_id}  -> download HTML
  POST /api/pdf/{job_id}       -> generate & return PDF

Run:  python app.py   (then open http://127.0.0.1:8000)
"""
import os
import sys
import json
import uuid
import time
import threading
import tempfile

# ── 路径兼容：源码模式 vs PyInstaller 冻结模式 ──
if getattr(sys, "frozen", False):
    # 冻结后，数据文件（static 等）被解压到 sys._MEIPASS
    BASE = sys._MEIPASS
else:
    BASE = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, BASE)

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import pdf_extract
import smart_extract
import translate_paper
import translator
import html_builder

STATIC_DIR = os.path.join(BASE, "static")
# 运行产物写到系统临时目录，避免冻结后 _MEIPASS 只读
OUTPUT = os.path.join(tempfile.gettempdir(), "pagewhisper_output")
os.makedirs(OUTPUT, exist_ok=True)

app = FastAPI(title="PDF 中英对照翻译工具")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/output", StaticFiles(directory=OUTPUT), name="output")

# Job state store
_jobs: dict = {}      # job_id -> {status, stage, percent, elapsed, token_info, ...}
_lock = threading.Lock()


def _run_translation(job: str, work: str, figdir: str, pdf_path: str,
                     engine: str, api_key: str, base_url: str, model: str,
                     translate_refs: bool, keep_original: bool, workers: int,
                     smart_mode: bool, translate_mode: str = "pipeline"):
    """Background translation task."""
    t0 = time.time()

    def _update(stage: str, percent: int, sub=None):
        with _lock:
            j = _jobs.get(job)
            if j:
                j["stage"] = stage
                j["percent"] = percent
                j["elapsed"] = round(time.time() - t0, 1)
                if sub:
                    j.setdefault("sub_stages", []).append(sub)

    try:
        # ── One-shot LLM mode: one API call produces complete HTML ──
        if translate_mode == "oneshot":
            if not api_key:
                raise ValueError("一次性 LLM 模式需要 API Key")
            _update("正在调用 LLM 翻译全文...", 10)
            html = translate_paper.translate_paper(
                pdf_path, api_key, base_url=base_url, model=model,
            )
            _update("LLM 翻译完成，正在提��图片...", 80)

            # Extract figures
            images = []
            import fitz
            with fitz.open(pdf_path) as d:
                for pno in range(len(d)):
                    page = d[pno]
                    try:
                        for info in page.get_image_info():
                            bbox = info.get("bbox")
                            if not bbox: continue
                            x0, y0, x1, y1 = bbox
                            if (x1-x0) < 60 or (y1-y0) < 60: continue
                            fn = f"fig_{pno+1}_{len(images)+1}.png"
                            pix = page.get_pixmap(clip=fitz.Rect(x0,y0,x1,y1), matrix=fitz.Matrix(2,2))
                            pix.save(os.path.join(figdir, fn))
                            images.append({"fig_no": len(images)+1, "img": "figures/"+fn})
                    except Exception:
                        pass

            # Insert figures at LLM's markers (<!-- FIG_N -->)
            if images:
                import re as _re
                for img in images:
                    n = img["fig_no"]
                    marker = f"<!-- FIG_{n} -->"
                    figure_tag = (
                        f'\n<figure><img src="{img["img"]}" alt="Fig {n}" style="max-width:100%;border:1px solid #ddd;">'
                        f'<figcaption style="font-size:0.85em;color:#555;margin-top:4px;">'
                        f'图 {n}（Fig. {n}）</figcaption></figure>\n'
                    )
                    if marker in html:
                        html = html.replace(marker, figure_tag)

                # Clean up any remaining unmatched markers
                html = _re.sub(r"<!--\s*FIG_\d+\s*-->", "", html)

                # Append figures that weren't placed yet
                remaining = [img for img in images if img["img"] not in html]
                if remaining:
                    fallback = '<h2>图表</h2>'
                    for img in remaining:
                        fallback += (
                            f'<figure><img src="{img["img"]}" alt="Fig {img["fig_no"]}" style="max-width:100%;border:1px solid #ddd;">'
                            f'<figcaption style="font-size:0.85em;color:#555;margin-top:4px;">图 {img["fig_no"]}</figcaption></figure>'
                        )
                    html = html.replace("</body>", fallback + "\n</body>")

            with open(os.path.join(work, "index.html"), "w", encoding="utf-8") as f:
                f.write(html)

            elapsed = round(time.time() - t0, 1)
            with _lock:
                j = _jobs.get(job)
                if j:
                    j["status"] = "done"; j["stage"] = "完成"; j["percent"] = 100
                    j["elapsed"] = elapsed; j["engine"] = "oneshot-" + engine
                    j["token_info"] = {"total_tokens": 0}
                    j["stats"] = {"pages": 0, "text_blocks": 0, "figures": len(images)}
                    j["view_url"] = f"/output/{job}/index.html"
            return

        # ── Pipeline mode ──
        _update("抽取PDF文本与图片...", 5)
        if smart_mode and api_key:
            doc = smart_extract.smart_extract(
                pdf_path, figdir, api_key, base_url=base_url, model=model,
                translate_refs=translate_refs,
            )
        else:
            doc = pdf_extract.extract_document(pdf_path, figdir, translate_refs=translate_refs)
        _update("抽取完成", 15,
                f"共{doc['stats']['pages']}页, {doc['stats']['text_blocks']}段, {doc['stats']['figures']}图")

        # Collect translatable text
        translatable = [it for it in doc["flow"]
                        if it["kind"] == "text" and it.get("translatable", True)]
        texts = [it["text"] for it in translatable]
        _update("翻译中...", 20, f"待翻译{len(texts)}段")

        if engine == "auto":
            engine = "openai" if api_key else "google"

        zh_list, token_info = translator.translate(
            texts, engine=engine, api_key=api_key,
            base_url=base_url, model=model, workers=workers,
            progress_callback=lambda pct: _update("翻译中...", pct),
        )
        _update("翻译完成", 85)

        tmap = {t: z for t, z in zip(texts, zh_list)}
        title = doc.get("title", "")

        html = html_builder.build_html(doc, tmap, title, keep_original=keep_original)
        with open(os.path.join(work, "index.html"), "w", encoding="utf-8") as f:
            f.write(html)

        with open(os.path.join(work, "meta.json"), "w", encoding="utf-8") as f:
            json.dump({
                "doc": doc, "tmap": tmap,
                "keep_original": keep_original,
            }, f, ensure_ascii=False)

        elapsed = round(time.time() - t0, 1)
        with _lock:
            j = _jobs.get(job)
            if j:
                j["status"] = "done"
                j["stage"] = "完成"
                j["percent"] = 100
                j["elapsed"] = elapsed
                j["engine"] = engine
                j["token_info"] = token_info
                j["stats"] = doc["stats"]
                j["view_url"] = f"/output/{job}/index.html"

    except Exception as e:
        with _lock:
            j = _jobs.get(job)
            if j:
                j["status"] = "error"
                j["stage"] = f"失败: {e}"
                j["elapsed"] = round(time.time() - t0, 1)


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.post("/api/translate")
async def api_translate(
    file: UploadFile = File(...),
    engine: str = Form("auto"),
    api_key: str = Form(""),
    base_url: str = Form(""),
    model: str = Form(""),
    translate_refs: bool = Form(False),
    keep_original: bool = Form(True),
    workers: int = Form(3),
    smart_mode: bool = Form(False),
    translate_mode: str = Form("pipeline"),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return JSONResponse({"error": "请上传 PDF 文件"}, status_code=400)

    job = uuid.uuid4().hex[:8]
    work = os.path.join(OUTPUT, job)
    figdir = os.path.join(work, "figures")
    os.makedirs(figdir, exist_ok=True)
    pdf_path = os.path.join(work, "input.pdf")
    with open(pdf_path, "wb") as f:
        f.write(await file.read())

    with _lock:
        _jobs[job] = {
            "job_id": job,
            "status": "running",
            "stage": "准备中...",
            "percent": 0,
            "elapsed": 0,
            "engine": "",
            "token_info": {},
            "stats": {},
            "view_url": "",
        }

    t = threading.Thread(
        target=_run_translation,
        args=(job, work, figdir, pdf_path, engine, api_key, base_url, model,
              translate_refs, keep_original, workers, smart_mode, translate_mode),
        daemon=True,
    )
    t.start()
    return JSONResponse({"job_id": job})


@app.get("/api/status/{job_id}")
def job_status(job_id: str):
    with _lock:
        j = _jobs.get(job_id)
    if not j:
        raise HTTPException(404, "任务不存在")
    return JSONResponse(j)


@app.get("/api/download/{job_id}")
def download(job_id: str):
    p = os.path.join(OUTPUT, job_id, "index.html")
    if not os.path.exists(p):
        raise HTTPException(404, "任务不存在")
    return FileResponse(p, media_type="text/html", filename=f"{job_id}.html")


@app.get("/api/pdf/{job_id}")
@app.post("/api/pdf/{job_id}")
def make_pdf(job_id: str):
    work = os.path.join(OUTPUT, job_id)
    meta_path = os.path.join(work, "meta.json")
    if not os.path.exists(meta_path):
        raise HTTPException(404, "任务不存在，请先翻译")
    pdf_path = os.path.join(work, "output.pdf")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        html_builder.build_pdf(
            meta["doc"], meta["tmap"], pdf_path,
            figures_base=work,
            keep_original=meta.get("keep_original", True),
        )
    except Exception as e:
        return JSONResponse({"error": f"PDF 生成失败：{e}"}, status_code=500)
    return FileResponse(pdf_path, media_type="application/pdf", filename=f"{job_id}.pdf")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
