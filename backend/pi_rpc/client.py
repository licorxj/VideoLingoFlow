import asyncio
import json
import os
import sys
import time
import uuid
from collections import deque
from typing import Any, Awaitable, Callable

from .models import PiSessionInfo


class PiRpcError(RuntimeError):
    pass


EventListener = Callable[[dict[str, Any]], Awaitable[None]]


class PiRpcClient:
    def __init__(
        self,
        project_root: str,
        session_id: str,
        project_id: str,
        cwd: str,
        model: str,
        tools: list[str],
        system_prompt: str,
        node_path: str,
        cli_path: str,
        session_dir: str,
        env: dict[str, str],
        max_output_chars: int = 12000,
    ):
        now = time.time()
        self.info = PiSessionInfo(session_id, project_id, cwd, model, tools, now, now)
        self._project_root = project_root
        self._node_path = node_path
        self._cli_path = cli_path
        self._session_dir = session_dir
        self._env = env
        self._system_prompt = system_prompt
        self._max_output_chars = max_output_chars
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._listeners: set[EventListener] = set()
        self._waiters: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._write_lock = asyncio.Lock()
        self._prompt_lock = asyncio.Lock()
        self._event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=200)
        self._event_history: deque[dict[str, Any]] = deque(maxlen=200)
        self._stderr_tail: deque[str] = deque(maxlen=40)
        self._closed = False
        self._seq = 0

    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._event_history)

    @property
    def stderr_tail(self) -> list[str]:
        """最近 40 行子进程 stderr（用于诊断 Pi 内部错误）。"""
        return list(self._stderr_tail)

    async def start(self) -> None:
        if not os.path.isfile(self._node_path):
            raise PiRpcError(f"Node runtime not found: {self._node_path}")
        if not os.path.isfile(self._cli_path):
            raise PiRpcError(f"Pi CLI not built: {self._cli_path}")
        os.makedirs(self._session_dir, exist_ok=True)
        args = [
            self._node_path,
            self._cli_path,
            "--mode",
            "rpc",
            "--provider",
            "videolingo",
            "--model",
            self.info.model,
            "--system-prompt",
            self._system_prompt,
            "--tools",
            ",".join(self.info.tools),
            "--session-dir",
            self._session_dir,
            "--no-extensions",
            "--extension",
            os.path.join(self._project_root, "data", "workspace", "pi-agent-config", "path-policy.mjs"),
            "--no-skills",
            "--no-context-files",
            "--no-approve",
        ]
        child_env = os.environ.copy()
        child_env["NODE_NO_WARNINGS"] = "1"
        child_env["PI_CODING_AGENT_DIR"] = os.path.join(self._project_root, "data", "workspace", "pi-agent-config")
        child_env["VIDEOLINGO_PI_API_KEY"] = self._env.get("OPENAI_API_KEY", "123")
        child_env["PATH"] = self._env.get("PATH") or child_env.get("PATH", "")
        for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "NO_PROXY", "VIDEOLINGO_PI_PATH_POLICY"):
            if self._env.get(key):
                child_env[key] = self._env[key]
        self._process = await asyncio.create_subprocess_exec(
            *args,
            cwd=self.info.cwd,
            env=child_env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        # Long thinking/text deltas arrive as single JSON lines; raise the asyncio
        # StreamReader line limit (default 64 KiB) so readline() does not raise
        # "Separator is found, but chunk is longer than limit".
        for stream in (self._process.stdout, self._process.stderr):
            if stream is not None and hasattr(stream, "_limit"):
                stream._limit = 4 * 1024 * 1024
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())

    async def _read_stdout(self) -> None:
        assert self._process and self._process.stdout
        try:
            while True:
                raw = await self._process.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace")
                if line.endswith("\n"):
                    line = line[:-1]
                if line.endswith("\r"):
                    line = line[:-1]
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    await self._publish({"type": "pi_error", "error": "Pi returned invalid JSON"})
                    continue
                request_id = payload.get("id")
                waiter = self._waiters.get(request_id) if request_id else None
                if waiter and not waiter.done() and payload.get("type") == "response":
                    waiter.set_result(payload)
                else:
                    await self._publish(payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._publish({"type": "pi_error", "error": str(exc)[: self._max_output_chars]})
        finally:
            self.info.closed = True
            self.info.streaming = False
            for waiter in self._waiters.values():
                if not waiter.done():
                    waiter.set_exception(PiRpcError("Pi process closed"))
            self._waiters.clear()
            await self._publish({"type": "pi_closed"})

    async def _read_stderr(self) -> None:
        assert self._process and self._process.stderr
        try:
            while True:
                raw = await self._process.stderr.readline()
                if not raw:
                    break
                self._stderr_tail.append(raw.decode("utf-8", errors="replace").strip()[:1000])
        except asyncio.CancelledError:
            raise

    async def _publish(self, event: dict[str, Any]) -> None:
        if event.get("type") == "message_update":
            delta = event.get("assistantMessageEvent", {})
            if delta.get("type") == "text_delta":
                event = {**event, "assistantMessageEvent": {**delta, "delta": str(delta.get("delta", ""))[: self._max_output_chars]}}
        self.info.last_activity = time.time()
        if event.get("type") in {"agent_start", "agent_end", "agent_settled", "message_end", "tool_execution_end"}:
            self.info.message_count += 1
        if event.get("type") in {"agent_end", "agent_settled", "pi_closed"}:
            self.info.streaming = False
        if event.get("type") == "agent_start":
            self.info.streaming = True
        event = {**event, "seq": self._seq}
        self._seq += 1
        self.info.seq = self._seq
        self._event_history.append(event)
        try:
            self._event_queue.put_nowait(event)
        except asyncio.QueueFull:
            self._event_queue.get_nowait()
            self._event_queue.put_nowait(event)
        await asyncio.gather(*(listener(event) for listener in tuple(self._listeners)), return_exceptions=True)

    def subscribe(self, listener: EventListener) -> Callable[[], None]:
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    async def next_event(self, timeout: float = 30) -> dict[str, Any]:
        return await asyncio.wait_for(self._event_queue.get(), timeout=timeout)

    async def command(self, command: dict[str, Any], timeout: float = 30) -> dict[str, Any]:
        if self._closed or not self._process or not self._process.stdin:
            raise PiRpcError("Pi session is closed")
        request_id = command.setdefault("id", uuid.uuid4().hex)
        loop = asyncio.get_running_loop()
        waiter = loop.create_future()
        self._waiters[request_id] = waiter
        try:
            async with self._write_lock:
                self._process.stdin.write((json.dumps(command, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
                await self._process.stdin.drain()
            response = await asyncio.wait_for(waiter, timeout=timeout)
            if not response.get("success", True):
                raise PiRpcError(str(response.get("error", "Pi command failed")))
            self.info.last_activity = time.time()
            return response
        finally:
            self._waiters.pop(request_id, None)

    async def prompt(self, message: str, streaming_behavior: str | None, timeout: float) -> dict[str, Any]:
        async with self._prompt_lock:
            command: dict[str, Any] = {"type": "prompt", "message": message}
            if streaming_behavior:
                command["streamingBehavior"] = streaming_behavior
            return await self.command(command, timeout)

    async def abort(self, timeout: float = 10) -> dict[str, Any]:
        return await self.command({"type": "abort"}, timeout)

    async def close(self) -> None:
        if self._closed:
            return
        if self._process and self._process.stdin:
            try:
                await self.abort(3)
            except Exception:
                pass
            self._process.stdin.close()
        if self._process:
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
        for task in (self._reader_task, self._stderr_task):
            if task:
                task.cancel()
        self._closed = True
        self.info.closed = True
