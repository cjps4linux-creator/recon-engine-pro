#!/usr/bin/env python3
"""
Recon Engine Pro — Desktop Launcher
=====================================
Starts the FastAPI backend and opens the PyWebView desktop window.
"""
import os
import sys
import time
import subprocess
try:
    import webview
except Exception:
    webview = None
import urllib.request

# ============================================================
# PATHS
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(BASE_DIR, "backend")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
CORP_RECON_DIR = os.path.join(BASE_DIR, "..", "corp-recon-engine")

# Ensure corp-recon-engine is in Python path
sys.path.insert(0, CORP_RECON_DIR)
sys.path.insert(0, BACKEND_DIR)

# ============================================================
# START BACKEND
# ============================================================
def start_backend():
    """Launch uvicorn server in background."""
    env = os.environ.copy()
    env["PYTHONPATH"] = CORP_RECON_DIR + os.pathsep + BACKEND_DIR

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app",
         "--host", "127.0.0.1", "--port", "8765",
         "--log-level", "warning"],
        cwd=BACKEND_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    )
    return proc

def wait_for_server(timeout=30):
    """Poll until backend is ready."""
    for _ in range(timeout * 10):
        try:
            urllib.request.urlopen("http://127.0.0.1:8765/api/health", timeout=1)
            return True
        except Exception:
            time.sleep(0.1)
    return False

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    print("Starting Recon Engine Pro…")

    # Start backend
    backend_proc = start_backend()
    print(f"Backend PID: {backend_proc.pid}")

    # Wait for ready
    print("Waiting for backend to start…")
    if not wait_for_server():
        print("ERROR: Backend failed to start within timeout")
        sys.exit(1)
    print("Backend ready.")

    # Open desktop window pointing at frontend
    frontend_url = "http://127.0.0.1:8765/app"

    if webview is None:
        import webbrowser
        webbrowser.open(frontend_url)
        print("Opened in default browser.")
    else:
        window = webview.create_window(
        title="Recon Engine Pro",
        url=frontend_url,
        width=1280,
        height=800,
        min_size=(960, 600),
        resizable=True,
        frameless=False,
        text_select=True,
    )

        def on_closing():
            # Graceful shutdown
            print("Shutting down…")
            try:
                backend_proc.terminate()
                backend_proc.wait(timeout=5)
            except Exception:
                backend_proc.kill()
            print("Goodbye.")

        window.events.closing += on_closing

        webview.start(debug=False, http_server=False)
