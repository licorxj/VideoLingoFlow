import http.server
import json
import subprocess
import sys
import os
import threading

BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "12002"))
MANAGER_PORT = 12003

_backend_process = None
_lock = threading.Lock()

def get_backend_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")

class ServiceHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self._send_json({"status": "ok"})
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        global _backend_process
        if self.path == "/start":
            with _lock:
                if _backend_process and _backend_process.poll() is None:
                    self._send_json({"status": "already_running", "pid": _backend_process.pid})
                    return
                try:
                    backend_dir = get_backend_dir()
                    python_exe = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend", "venv", "Scripts", "python.exe")
                    _backend_process = subprocess.Popen(
                        [python_exe, "-m", "uvicorn", "app.main:app",
                         "--host", "0.0.0.0", "--port", str(BACKEND_PORT)],
                        cwd=backend_dir,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    self._send_json({"status": "started", "pid": _backend_process.pid})
                except Exception as e:
                    self._send_json({"status": "error", "message": str(e)}, 500)
        elif self.path == "/stop":
            with _lock:
                if _backend_process and _backend_process.poll() is None:
                    _backend_process.terminate()
                    _backend_process = None
                    self._send_json({"status": "stopped"})
                else:
                    self._send_json({"status": "not_running"})
        else:
            self._send_json({"error": "not found"}, 404)

if __name__ == "__main__":
    server = http.server.HTTPServer(("127.0.0.1", MANAGER_PORT), ServiceHandler)
    print(f"Service Manager running on port {MANAGER_PORT}")
    server.serve_forever()
