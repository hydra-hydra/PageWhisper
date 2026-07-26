"""PageWhisper 一键启动器。

本地运行：自动启动 FastAPI 服务并打开浏览器。
"""
import os
import sys
import time
import threading
import webbrowser

import socket

import uvicorn

PORT = int(os.environ.get("PORT", "8000"))
HOST = os.environ.get("HOST", "127.0.0.1")


def _find_free_port(host: str, start: int) -> int:
    """若 start 端口被占用，自动向上查找可用端口。"""
    for port in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    return start  #  fallback：让 uvicorn 自行报错


def _open_browser(port: int) -> None:
    time.sleep(1.5)
    try:
        webbrowser.open(f"http://{HOST}:{port}")
    except Exception:
        pass


if __name__ == "__main__":
    import app as _app

    actual_port = _find_free_port(HOST, PORT)
    if actual_port != PORT:
        print(f"\n  端口 {PORT} 已被占用，已自动切换到 {actual_port}")
    threading.Thread(target=_open_browser, args=(actual_port,), daemon=True).start()
    print(f"\n  PageWhisper 启动中 → http://{HOST}:{actual_port}\n")
    sys.stdout.flush()
    uvicorn.run(_app.app, host=HOST, port=actual_port, log_level="info")
