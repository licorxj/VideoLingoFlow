import sys, math
sys.path.insert(0, "backend")
from utils.sentence_split_core import split_chinese_by_chars, split_english_by_chars

def check(tag, chunks, text, max_length, space_sep):
    joined = " ".join(chunks) if space_sep else "".join(chunks)
    assert joined == text, f"[{tag}] partition broken: {joined!r} != {text!r}"
    lens = [len(c) for c in chunks]
    for c in chunks:
        assert len(c) <= max_length, f"[{tag}] chunk over budget: {len(c)} > {max_length}"
    print(f"[{tag}] max={max_length} chunks={len(chunks)} lens={lens}")
    # tiny tail check: no chunk shorter than half of max_length unless it's the only chunk
    if len(chunks) > 1:
        for c in chunks:
            assert len(c) >= max_length / 2 - 1, (
                f"[{tag}] tiny tail chunk ({len(c)} chars) < max/2={max_length/2:.0f}"
            )

# Chinese: 35 chars, max 30 -> old greedy would leave a ~5-char tail
zh = "我们今天去公园散步然后去超市买了很多东西并且吃了晚饭才回家睡觉。"
check("zh-35", split_chinese_by_chars(zh, 30, has_jieba=False), zh, 30, False)

# Chinese: 95 chars, max 30 -> old greedy leaves a ~5-char tail
zh2 = ("春眠不觉晓处处闻啼鸟夜来风雨声花落知多少白日依山尽黄河入海流欲穷千里目"
       "更上一层楼床前明月光疑是地上霜举头望明月低头思故乡")
check("zh-95", split_chinese_by_chars(zh2, 30, has_jieba=False), zh2, 30, False)

# English long sentence, max 22
en = "Hello world this is a relatively long English sentence that needs to be split into balanced pieces for readability."
check("en", split_english_by_chars(en, 22), en, 22, True)

print("ALL OK")
