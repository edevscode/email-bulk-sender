import os
import sys
import webbrowser
import threading
import time
import socket
import urllib.request
import urllib.error

def wait_for_server(host='127.0.0.1', port=8501, timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False

def wait_for_http_ready(url: str, timeout=30) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                status = getattr(resp, "status", None)
                if status is None or (200 <= status < 400):
                    return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                time.sleep(0.5)
                continue
            time.sleep(0.5)
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.5)
    return False

def main() -> None:
    os.environ.setdefault("BES_HOST", "0.0.0.0")
    os.environ.setdefault("BES_PORT", "8501")
    host = os.environ.get("BES_HOST", "0.0.0.0")
    port = int(os.environ.get("BES_PORT", "8501"))

    def open_browser():
        if wait_for_http_ready(f"http://127.0.0.1:{port}/health"):
            webbrowser.open(f"http://127.0.0.1:{port}")
            return
        webbrowser.open(f"http://127.0.0.1:{port}")

    threading.Thread(target=open_browser, daemon=True).start()
    import uvicorn

    sys.exit(
        uvicorn.run(
            "server:app",
            host=host,
            port=port,
            log_level="info",
        )
    )


if __name__ == "__main__":
    main()
