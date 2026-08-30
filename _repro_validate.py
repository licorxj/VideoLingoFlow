import os, json, tempfile, shutil, sys
sys.path.insert(0, os.path.abspath("."))
from backend.steps.s_asr_result_validate import S_ASRResultValidate

base = tempfile.mkdtemp()
cache = os.path.join(base, "cache")
os.makedirs(cache, exist_ok=True)

UP = "asr_result.json"          # 上游 ASR 节点输出（无 node_id 后缀）
SELF = "asr_result_validate123.json"

upstream = {"text": "hello world", "segments": [{"text": "hello world", "words": [{"word": "hello"}, {"word": "world"}]}]}
stale = {"text": "STALE OLD OUTPUT", "segments": []}  # 本节点上一次写出的旧输出

with open(os.path.join(cache, UP), "w", encoding="utf-8") as f:
    json.dump(upstream, f)
with open(os.path.join(cache, SELF), "w", encoding="utf-8") as f:
    json.dump(stale, f)

step = S_ASRResultValidate()
step._node_id = "validate123"

# 情形 1：step_inputs['json'] 为空（上游经 step_inputs.update 只给了 subtitle 键），走兜底
step._step_inputs = {}
data1, src1 = step._load_asr(base)
print("[情形1 空输入->兜底] src=", os.path.basename(src1), "| text=", data1.get("text"))

# 情形 2：step_inputs['json'] 指向本节点自己旧输出（错误连线/自环）——应被排除并回退上游
step._step_inputs = {"json": os.path.join(cache, SELF)}
data2, src2 = step._load_asr(base)
print("[情形2 json=自身旧输出] src=", os.path.basename(src2), "| text=", data2.get("text"))

# 情形 3：step_inputs['json'] 正确指向上游
step._step_inputs = {"json": os.path.join(cache, UP)}
data3, src3 = step._load_asr(base)
print("[情形3 json=上游] src=", os.path.basename(src3), "| text=", data3.get("text"))

shutil.rmtree(base)
