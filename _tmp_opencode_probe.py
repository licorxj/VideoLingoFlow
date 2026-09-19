"""临时探测：opencode run --format json 的事件结构与退出码（流式读取，跑完即删）。"""
import json
import os
import subprocess
import sys
import tempfile
import threading

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

OPENCODE_EXE = r"C:\Users\Administrator\.cherrystudio\bin\opencode.exe"
cwd = tempfile.mkdtemp(prefix="oc_test_")
print("cwd:", cwd, flush=True)

# build 是 subagent（会回退到很重的 Sisyphus）；这里用最轻量的 primary agent 快速拿到事件结构
cmd = [
    OPENCODE_EXE, "run",
    "Reply with the single word OK and nothing else.",
    "--format", "json", "--print-logs",
    "--agent", "title",
    "-m", "google/gemini-3.8-flash",
    "--dir", cwd,
]

p = subprocess.Popen(
    cmd, cwd=cwd, stdin=subprocess.DEVNULL,
    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, encoding="utf-8", errors="replace",
)

out_lines, err_lines = [], []


def reader(stream, sink, tag):
    try:
        for line in stream:
            sink.append(line)
            print(f"[{tag}] {line.rstrip()[:400]}", flush=True)
    finally:
        stream.close()


t_out = threading.Thread(target=reader, args=(p.stdout, out_lines, "OUT"), daemon=True)
t_err = threading.Thread(target=reader, args=(p.stderr, err_lines, "ERR"), daemon=True)
t_out.start()
t_err.start()

try:
    rc = p.wait(timeout=240)
except subprocess.TimeoutExpired:
    p.kill()
    rc = "KILLED_BY_TIMEOUT"

t_out.join(timeout=5)
t_err.join(timeout=5)

print("\n===== 汇总 =====", flush=True)
print("returncode:", rc, flush=True)
print("stdout lines:", len(out_lines), " stderr lines:", len(err_lines), flush=True)

types, samples = [], {}
for line in out_lines:
    line = line.strip()
    if not line:
        continue
    try:
        obj = json.loads(line)
    except Exception:
        continue
    if isinstance(obj, dict):
        t = obj.get("type")
        types.append(t)
        if t not in samples:
            samples[t] = json.dumps(obj, ensure_ascii=False)[:500]

print("=== 事件 type 序列（前 60） ===", flush=True)
print(types[:60], flush=True)
print("=== 各 type 首例 ===", flush=True)
for t, s in samples.items():
    print(f"[{t}] {s}", flush=True)
