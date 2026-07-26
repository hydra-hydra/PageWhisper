"""Token-efficient translation layer with parallel processing and usage tracking.

Engine:
- "openai": any OpenAI-compatible /v1/chat/completions endpoint
- "google": free Google Translate fallback (no key needed)

Returns (translations, token_info) where token_info = {prompt_tokens, completion_tokens, total_tokens}.
"""
import json
import re
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


def _chunk(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _extract_json_array(s: str):
    try:
        arr = json.loads(s)
        if isinstance(arr, list):
            return arr
    except Exception:
        pass
    m = re.search(r"\[.*\]", s, re.S)
    if m:
        try:
            arr = json.loads(m.group(0))
            if isinstance(arr, list):
                return arr
        except Exception:
            return None
    return None


def _single(chunk: list, headers: dict, base_url: str, model: str,
            sys_prompt: str, timeout: int = 120):
    """Translate one chunk, return (translations, token_info)."""
    user = "Translate this JSON array:\n" + json.dumps(list(chunk), ensure_ascii=False)
    try:
        r = requests.post(
            base_url.rstrip("/") + "/chat/completions",
            headers=headers,
            json={"model": model, "temperature": 0.3,
                  "messages": [{"role": "system", "content": sys_prompt},
                               {"role": "user", "content": user}]},
            timeout=timeout,
        )
        r.raise_for_status()
        body = r.json()
        content = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})
        tokens = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }

        arr = _extract_json_array(content)
        if arr is None or len(arr) != len(chunk):
            # Fallback: one-by-one
            results = []
            for t in chunk:
                try:
                    r2 = requests.post(
                        base_url.rstrip("/") + "/chat/completions",
                        headers=headers,
                        json={"model": model, "temperature": 0.3,
                              "messages": [{"role": "system", "content": sys_prompt},
                                           {"role": "user", "content": t}]},
                        timeout=60,
                    )
                    r2.raise_for_status()
                    b2 = r2.json()
                    results.append(b2["choices"][0]["message"]["content"].strip())
                    u2 = b2.get("usage", {})
                    tokens["prompt_tokens"] += u2.get("prompt_tokens", 0)
                    tokens["completion_tokens"] += u2.get("completion_tokens", 0)
                    tokens["total_tokens"] += u2.get("total_tokens", 0)
                except Exception:
                    results.append(t)
            return results, tokens
        return arr, tokens
    except Exception:
        return list(chunk), {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def translate(texts, engine="google", api_key="", base_url="",
              model="", glossary=None, chunk_size=60, workers=3,
              progress_callback=None) -> tuple:
    """Translate English strings to Simplified Chinese.

    Returns (translations: list, token_info: dict).
    translations is aligned 1:1 with texts (falls back to original on error).
    """
    token_info = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    if not texts:
        return [], token_info

    # ── Google Translate (parallel batches for speed) ──
    if engine == "google":
        from deep_translator import GoogleTranslator

        def _translate_chunk(chunk):
            tr = GoogleTranslator(source="en", target="zh-CN")
            try:
                return list(tr.translate_batch(list(chunk)))
            except Exception:
                result = []
                for t in chunk:
                    try:
                        result.append(tr.translate(t))
                    except Exception:
                        result.append(t)
                return result

        chunks = list(_chunk(texts, 30))
        total = len(chunks)

        if workers <= 1 or total <= 1:
            # Sequential
            out = []
            for i, ch in enumerate(chunks):
                out.extend(_translate_chunk(ch))
                if progress_callback:
                    progress_callback(int((i + 1) / total * 60) + 20)  # 20-80%
        else:
            # Multi-threaded Google
            chunk_order = {}
            with ThreadPoolExecutor(max_workers=min(workers, total)) as executor:
                futures = {executor.submit(_translate_chunk, ch): idx
                           for idx, ch in enumerate(chunks)}
                for fut in as_completed(futures):
                    idx = futures[fut]
                    try:
                        chunk_order[idx] = fut.result()
                    except Exception:
                        chunk_order[idx] = list(chunks[idx])
            out = []
            for idx in sorted(chunk_order):
                out.extend(chunk_order[idx])

        # Estimate tokens: ~1.3 chars per token for English
        total_chars = sum(len(t) for t in texts)
        token_info["total_tokens"] = int(total_chars / 1.3)
        token_info["prompt_tokens"] = token_info["total_tokens"]
        token_info["completion_tokens"] = 0
        return out, token_info

    # ── OpenAI-compatible LLM path ──
    if not base_url:
        base_url = "https://api.openai.com/v1"
    if not model:
        model = "gpt-4o-mini"

    sys_prompt = (
        "You are a professional scientific translator converting academic English into polished, "
        "publication-quality Simplified Chinese. Your translations should read like they were originally "
        "written in Chinese by a native scientist.\n\n"
        "## Translation Rules\n"
        "1. **Formal academic Chinese**: use formal, precise scientific prose. Avoid colloquialisms.\n"
        "2. **Technical terms**: on FIRST appearance only, append English in parentheses, "
        "e.g. '铁死亡（ferroptosis）'. On subsequent mentions, use either the Chinese term or the English "
        "abbreviation directly, whichever reads more naturally.\n"
        "3. **Gene/protein symbols**: keep in original case (ISCU, GPX4, MMP13, Col2a1). Do NOT translate.\n"
        "4. **Numbers, statistics, units**: preserve exactly as-is (n=8, p<0.05, 100 μm, etc.)\n"
        "5. **Section headings**: translate into natural Chinese (e.g. 'Introduction' → '引言', "
        "'Results' → '结果', 'Discussion' → '讨论', 'Methods' → '方法', "
        "'Abstract' → '摘要', 'Data availability' → '数据可用性', "
        "'Acknowledgements' → '致谢', 'Author contributions' → '作者贡献', "
        "'Competing interests' → '利益冲突声明', 'References' → '参考文献')\n"
        "6. **Paragraph coherence**: if input is fragmented across multiple items, produce a single "
        "coherent Chinese paragraph. Maintain the logical flow.\n"
        "7. **Figure citations**: preserve as-is. If the text says '(Fig. 1a)', keep '(Fig. 1a)'.\n\n"
        "## Response Format\n"
        "Respond with a JSON array of strings, exactly ONE translation per input item, in the same order. "
        "Each translation should be the complete Chinese version of that item.\n"
        "Do NOT add numbering, labels, bullets, or any commentary."
    )
    if glossary:
        g = "; ".join(f"{k} -> {v}" for k, v in glossary.items())
        sys_prompt += f" Use these established translations: {g}."

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    chunks = list(_chunk(texts, chunk_size))

    if workers <= 1 or len(chunks) <= 1:
        # Sequential
        out = []
        for i, ch in enumerate(chunks):
            tr, ti = _single(ch, headers, base_url, model, sys_prompt)
            out.extend(tr)
            for k in token_info:
                token_info[k] += ti.get(k, 0)
            if progress_callback:
                progress_callback(int((i + 1) / len(chunks) * 60) + 20)
        return out, token_info

    # Parallel with thread pool
    chunk_order = {}  # idx -> result
    done_count = [0]  # mutable counter for thread safety
    import threading as _thr
    _pc_lock = _thr.Lock()
    with ThreadPoolExecutor(max_workers=min(workers, len(chunks))) as executor:
        futures = {
            executor.submit(_single, ch, headers, base_url, model, sys_prompt): idx
            for idx, ch in enumerate(chunks)
        }
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                tr, ti = fut.result()
                chunk_order[idx] = (tr, ti)
            except Exception:
                ch = chunks[idx]
                chunk_order[idx] = (list(ch), {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
            with _pc_lock:
                done_count[0] += 1
                if progress_callback:
                    progress_callback(int(done_count[0] / len(chunks) * 60) + 20)

    out = []
    for idx in sorted(chunk_order):
        tr, ti = chunk_order[idx]
        out.extend(tr)
        for k in token_info:
            token_info[k] += ti.get(k, 0)

    return out, token_info
