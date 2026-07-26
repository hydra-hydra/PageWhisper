"""PageWhisper 一键启动器。

本地运行：自动启动 FastAPI 服务并打开浏览器。
"""
import os
import sys
import time
import threading
import webbrowser

import uvicorn

PORT = int(os.environ.get("PORT", "8000"))
HOST = os.environ.get("HOST", "127.0.0.1")


def _open_browser() -> None:
    time.sleep(1.5)
    try:
        webbrowser.open(f"http://{HOST}:{PORT}")
    except Exception:
        pass


if __name__ == "__main__":
    import app as _app
    threading.Thread(target=_open_browser, daemon=True).start()
    print(f"\n  PageWhisper 启动中 → http://{HOST}:{PORT}\n")
    sys.stdout.flush()
    uvicorn.run(_app.app, host=HOST, port=PORT, log_level="info")
