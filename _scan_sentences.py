"""Read-only scan: report every sentence whose text != words (normalized)."""
import json, os, re, sys

BASE = r"Y:\VideoLingoLc\control_plane_workspaces\54b5cf7d96414923934f759e2be6f832\cache"
PATH = os.path.join(BASE, "sentences_node_2_1780807148463.json")

norm = lambda s: re.sub(r"[^\w\s]", "", re.sub(r"\s+", "", str(s or ""))).lower()

with open(PATH, encoding="utf-8") as f:
    data = json.load(f)

sents = data if isinstance(data, list) else data.get("sentences") or data.get("segments") or []
print(f"loaded {len(sents)} sentences")
bad = 0
for s in sents:
    text = s.get("text") or ""
    words = s.get("words") or []
    tn = norm(text)
    wn = norm("".join(w.get("word", "") for w in words))
    if tn != wn:
        bad += 1
        print(f"  id={s.get('id')} prefix_ok={wn.startswith(tn)} text_len={len(tn)} word_len={len(wn)}")
        print(f"    text : {text!r}")
        print(f"    words: {[w.get('word') for w in words]!r}")
print(f"\nTOTAL inconsistent: {bad}/{len(sents)}")
