"""一次性脚本：把指定的内置节点同步到 frontend/src/lib/fallbackNodeTypes.ts。"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.config.builtin_node_types import BUILTIN_NODE_TYPES  # noqa: E402

FALLBACK = os.path.join(ROOT, "frontend", "src", "lib", "fallbackNodeTypes.ts")
ORDER = ["id", "name", "category", "description", "icon", "color",
         "inputs", "outputs", "defaultConfig", "configFields"]
TARGETS = ["kie_media_host"]

with open(FALLBACK, "r", encoding="utf-8") as f:
    content = f.read()

added = []
for target in TARGETS:
    if f'"id": "{target}"' in content:
        print("already present, skip:", target)
        continue
    node = next((n for n in BUILTIN_NODE_TYPES if n["id"] == target), None)
    if node is None:
        print("NOT FOUND in builtin:", target)
        continue

    obj = {k: node[k] for k in ORDER if k in node}
    obj["isBuiltIn"] = True
    body = json.dumps(obj, ensure_ascii=False, indent=2)
    body = "\n".join(("  " + ln) if ln.strip() else ln for ln in body.splitlines())

    idx = content.rfind("\n];")
    if idx == -1:
        raise SystemExit("closing marker not found")
    content = content[:idx] + ",\n" + body + content[idx:]
    added.append(target)

with open(FALLBACK, "w", encoding="utf-8") as f:
    f.write(content)

print("synced:", added)
