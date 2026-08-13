"""Log streaming: captures stdout/stderr + tails log files, broadcasts via WebSocket."""
import asyncio
import sys
import io
import os
import time
from collections import deque
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

LOG_BUFFER_SIZE = 5000
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs")


class LogBroadcaster:
    def __init__(self):
        self._clients: list[WebSocket] = []
        self._buffer: deque = deque(maxlen=LOG_BUFFER_SIZE)
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self._clients.append(ws)
        for entry in list(self._buffer):
            try:
                await ws.send_json(entry)
            except Exception:
                break

    async def disconnect(self, ws: WebSocket):
        async with self._lock:
            if ws in self._clients:
                self._clients.remove(ws)

    async def broadcast(self, level: str, message: str, source: str = "stdout"):
        entry = {"ts": time.time(), "level": level, "msg": message, "source": source}
        self._buffer.append(entry)
        dead = []
        async with self._lock:
            for c in self._clients:
                try:
                    await c.send_json(entry)
                except Exception:
                    dead.append(c)
            for d in dead:
                self._clients.remove(d)


broadcaster = LogBroadcaster()


class _StreamRedirector(io.TextIOBase):
    """Captures sys.stdout or sys.stderr and broadcasts lines to WebSocket clients."""
    def __init__(self, original, level: str):
        self._original = original
        self._level = level
        self._buf = ""

    def write(self, data):
        if data is None:
            return 0
        text = str(data)
        self._buf += text
        self._flush_lines()
        # Also write to original so terminal still works
        try:
            self._original.write(data)
        except Exception:
            pass
        return len(text)

    def _flush_lines(self):
        if "\n" in self._buf:
            lines = self._buf.split("\n")
            self._buf = lines[-1]
            for line in lines[:-1]:
                line = line.strip()
                if line:
                    self._safe_broadcast(line)

    def _safe_broadcast(self, line: str):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(broadcaster.broadcast(self._level, line))
            else:
                loop.create_task(broadcaster.broadcast(self._level, line))
        except RuntimeError:
            pass

    def flush(self):
        if self._buf.strip():
            self._safe_broadcast(self._buf.strip())
            self._buf = ""

    def fileno(self):
        return self._original.fileno()

    @property
    def encoding(self):
        return "utf-8"

    def isatty(self):
        return False


class _FileTailer:
    """Tails a log file and broadcasts new lines via the broadcaster."""
    def __init__(self, filepath: str, level: str = "info"):
        self._filepath = filepath
        self._level = level
        self._offset = 0
        self._task = None

    async def start(self):
        if os.path.exists(self._filepath):
            self._offset = os.path.getsize(self._filepath)
        self._task = asyncio.create_task(self._tail_loop())

    async def _tail_loop(self):
        while True:
            try:
                if os.path.exists(self._filepath):
                    size = os.path.getsize(self._filepath)
                    if size < self._offset:
                        self._offset = 0  # File was truncated
                    if size > self._offset:
                        with open(self._filepath, "r", encoding="utf-8", errors="replace") as f:
                            f.seek(self._offset)
                            new_data = f.read()
                            self._offset = f.tell()
                        for line in new_data.split("\n"):
                            line = line.strip()
                            if line:
                                await broadcaster.broadcast(self._level, line, source="file")
            except Exception:
                pass
            await asyncio.sleep(1)

    def stop(self):
        if self._task:
            self._task.cancel()


_tailers: list[_FileTailer] = []


def install_log_redirectors():
    """Replace sys.stdout/sys.stderr with broadcast redirectors + start file tailers."""
    _orig_stdout = sys.stdout
    _orig_stderr = sys.stderr
    sys.stdout = _StreamRedirector(_orig_stdout, "info")
    sys.stderr = _StreamRedirector(_orig_stderr, "error")

    # Start tailing log files
    os.makedirs(LOG_DIR, exist_ok=True)
    for fname in os.listdir(LOG_DIR):
        if fname.endswith(".log"):
            fpath = os.path.join(LOG_DIR, fname)
            tailer = _FileTailer(fpath, "info")
            asyncio.get_event_loop().create_task(tailer.start())
            _tailers.append(tailer)


@router.websocket("/logs")
async def logs_ws(ws: WebSocket):
    await broadcaster.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await broadcaster.disconnect(ws)
