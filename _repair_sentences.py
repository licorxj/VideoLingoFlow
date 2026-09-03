"""Repair the cached sentence_split output for task 54b5cf7d96414923934f759e2be6f832.

Root cause (now fixed in code): `assign_words_by_char_offset` split a
boundary-straddling word's *timestamps* but copied its full *text* into both
sentences, so each sentence's `text` disagreed with its `words`.

Here we only fix the cached artifact: for every sentence whose words (concatenated,
normalized) != its text, we locate the text as a substring of the concatenated word
texts and slice each word's `word` field to the overlapping character window,
keeping the (already correct) per-sentence timestamps. This makes text == words
everywhere without touching the ASR source or any other field.
"""
import json
import os
import re
import shutil

BASE = r"Y:\VideoLingoLc\control_plane_workspaces\54b5cf7d96414923934f759e2be6f832\cache"
PATH = os.path.join(BASE, "sentences_node_2_1780807148463.json")

_clean = lambda s: re.sub(r"[^\w\s]", "", re.sub(r"\s+", "", str(s or ""))).lower()


def repair_one(sent):
    words = sent.get("words") or []
    if not words:
        return False
    wt_list = [_clean(w.get("word", "")) for w in words]
    W = "".join(wt_list)
    T = _clean(sent.get("text", ""))
    if W == T or not T:
        return False
    k = W.find(T)
    if k < 0:
        return False
    out = []
    pos = 0
    for w, wt in zip(words, wt_list):
        if pos >= k + len(T):
            break
        seg_start = max(pos, k)
        seg_end = min(pos + len(wt), k + len(T))
        if seg_end <= seg_start:
            pos += len(wt)
            continue
        wp0 = seg_start - pos
        take = seg_end - seg_start
        sub = dict(w)
        sub["word"] = wt[wp0:wp0 + take]
        out.append(sub)
        pos += len(wt)
    if _clean("".join(o["word"] for o in out)) == T:
        sent["words"] = out
        if out:
            if out[0].get("start") is not None:
                sent["start"] = out[0]["start"]
            if out[-1].get("end") is not None:
                sent["end"] = out[-1]["end"]
        return True
    return False


def main():
    shutil.copy2(PATH, PATH + ".bak")
    print(f"backup -> {PATH}.bak")

    with open(PATH, encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        sents = data
        is_list = True
    else:
        sents = data.get("sentences") or data.get("segments") or []
        is_list = False

    repaired = 0
    for s in sents:
        if repair_one(s):
            repaired += 1

    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # verify
    bad = 0
    for s in sents:
        tn = _clean(s.get("text", ""))
        wn = _clean("".join(w.get("word", "") for w in (s.get("words") or [])))
        if tn != wn:
            bad += 1
            print("  STILL BAD:", s.get("id"), repr(s.get("text")), [w.get("word") for w in s.get("words")])
    print(f"repaired {repaired} sentences; remaining inconsistent: {bad}/{len(sents)}")
    if bad == 0:
        print("OK: all sentences now consistent (text == words).")


if __name__ == "__main__":
    main()
