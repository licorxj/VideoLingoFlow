import json, sys
sys.path.insert(0, r"Y:\VideoLingoLc")
from backend.utils.sentence_split_core import assign_words_by_char_offset

asr_path = r"Y:\VideoLingoLc\control_plane_workspaces\54b5cf7d96414923934f759e2be6f832\cache\asr_result_node_2_1788054290141.json"
asr = json.load(open(asr_path, encoding="utf-8"))
seg10 = next(s for s in asr["segments"] if s["id"] == 10)
words = seg10["words"]
s_start, s_end = seg10["start"], seg10["end"]

# The 3 chunks the LLM/force split produced for this segment (from sentences output)
chunks = ["そんなに特に", "深い意味はないん", "ですけど。"]

res = assign_words_by_char_offset(words, chunks, s_start, s_end)

print(f"segment start={s_start} end={s_end}  (real last word end={words[-1]['end']})")
all_ok = True
prev_end = None
for i, ac in enumerate(res):
    print(f"\nchunk[{i}] '{ac['text']}'")
    print(f"  start={ac['start']} end={ac['end']} nwords={len(ac['words'])}")
    if ac["start"] is None or ac["end"] is None:
        all_ok = False
        print("  !! missing timestamp")
    if prev_end is not None and abs(ac["start"] - prev_end) > 0.05:
        all_ok = False
        print(f"  !! gap/overlap vs prev end {prev_end}: {ac['start']}")
    prev_end = ac["end"]
    if ac["end"] is not None and ac["end"] > s_end + 1e-3:
        all_ok = False
        print(f"  !! end {ac['end']} exceeds segment end {s_end}")
    for w in ac["words"]:
        print(f"    - {w['word']} {w['start']}-{w['end']}")

# time conservation: every original word's full duration must be distributed exactly once
orig_span = sum(float(w["end"]) - float(w["start"]) for w in words)
sub_span = 0.0
for ac in res:
    for w in ac["words"]:
        sub_span += float(w["end"]) - float(w["start"])
if abs(orig_span - sub_span) > 0.01:
    all_ok = False
    print(f"\n!! time not conserved: orig={orig_span:.4f} distributed={sub_span:.4f}")

# specific assertions from the bug report
s11 = res[1]
s12 = res[2]
has_hanain = any("はないん" in w["word"] for w in s11["words"])
s12_has_words = len(s12["words"]) > 0
s12_within = s12["end"] is not None and s12["end"] <= s_end + 1e-3
print("\n=== ASSERTIONS ===")
print("sentence11 covers 'はないん':", has_hanain)
print("sentence12 has words:", s12_has_words)
print("sentence12 end <= 29.12:", s12_within)
print("time conserved & contiguous & in-bounds:", all_ok)
assert has_hanain and s12_has_words and s12_within and all_ok, "FIX FAILED"
print("PASS")
