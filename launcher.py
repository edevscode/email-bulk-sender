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
    os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] = "false"
    os.environ["STREAMLIT_SERVER_PORT"] = "8501"
    os.environ["STREAMLIT_SERVER_ADDRESS"] = "0.0.0.0"
    os.environ["STREAMLIT_SERVER_BASE_URL_PATH"] = ""
    app_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")
    sys.argv = [
        "streamlit",
        "run",
        app_path,
        "--global.developmentMode=false",
        "--server.address=0.0.0.0",
        "--server.port=8501",
        "--server.baseUrlPath=",
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
    ]

    def open_browser():
        if wait_for_http_ready("http://127.0.0.1:8501/_stcore/health"):
            webbrowser.open("http://127.0.0.1:8501")
            return
        webbrowser.open("http://127.0.0.1:8501")

    threading.Thread(target=open_browser, daemon=True).start()
    from streamlit.web import cli as stcli

    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
