import re

from backend.llm.llm_client import LLMClient


def normalize_text(value: str):
    return re.sub(r"\s+", "", value or "")


def clean_text(value: str, chars_to_remove: str = "", wildcards: list[dict] | None = None, find_text: str = "", replace_text: str = ""):
    result = value or ""
    for item in wildcards or []:
        opening, closing = item.get("open", ""), item.get("close", "")
        if opening and closing:
            result = re.sub(re.escape(opening) + r"[\s\S]*?" + re.escape(closing), "", result)
    if chars_to_remove:
        result = result.translate(str.maketrans("", "", chars_to_remove))
    if find_text:
        result = result.replace(find_text, replace_text)
    return re.sub(r"\n{3,}", "\n\n", result).strip()


def split_text(value: str, symbols: list[str], max_length: int = 500):
    symbols = [item for item in symbols if item]
    if not symbols:
        raise ValueError("请至少选择一个分句符号")
    pattern = "(" + "|".join(re.escape(item) for item in sorted(symbols, key=len, reverse=True)) + ")"
    raw = re.split(pattern, value or "")
    result, current = [], ""
    for part in raw:
        current += part
        if part in symbols or len(current) >= max_length:
            item = current.strip()
            if item:
                result.append(item)
            current = ""
    if current.strip():
        result.append(current.strip())
    return result


def _source_limit(value: str, maximum: int = 100000):
    source = (value or "").strip()
    if not source:
        raise ValueError("没有可处理的文本")
    if len(source) > maximum:
        raise ValueError("文本超过处理上限")
    return source


def ai_split_sentences(value: str, max_length: int):
    source = _source_limit(value)
    system_prompt = "你是文本分句助手。只能按原文切分，不得改写、删减或新增字符。严格返回 JSON：{\"sentences\":[\"原文片段\"]}。"
    prompt = f"最大单句长度：{max_length}\n原文：\n{source}"
    response = LLMClient().chat("voiceforge_sentence_split", prompt, response_json=True, system_prompt=system_prompt, temperature=0.1)
    items = response.get("sentences") if isinstance(response, dict) else None
    if not isinstance(items, list) or not all(isinstance(item, str) and item.strip() for item in items):
        raise ValueError("LLM 未返回有效分句结果")
    result = [item.strip() for item in items]
    if normalize_text("".join(result)) != normalize_text(source):
        raise ValueError("LLM 分句结果与原文不一致")
    return result


def ai_extract_dialogue(value: str, character_names: list[str], narration_mode: bool, narration_style: str):
    source = _source_limit(value)
    system_prompt = "你是配音剧本分析助手。严格返回 JSON：{\"characters\":[{\"name\":\"角色名\",\"character_type\":\"角色类型\",\"note\":\"说明\"}],\"sentences\":[{\"speaker\":\"角色或旁白\",\"text\":\"原文朗读文本\",\"emotion\":\"情绪\",\"tone_description\":\"中文语气说明\"}]}。不得输出 Markdown。"
    prompt = f"模式：{'旁白加对话' if narration_mode else '仅对话'}\n旁白风格：{narration_style}\n已有角色：{', '.join(character_names)}\n原文：\n{source}"
    response = LLMClient().chat("voiceforge_dialogue_extract", prompt, response_json=True, system_prompt=system_prompt, temperature=0.2)
    if not isinstance(response, dict) or not isinstance(response.get("sentences"), list):
        raise ValueError("LLM 未返回有效对话结果")
    sentences = []
    for item in response["sentences"]:
        if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip():
            sentences.append({"speaker": str(item.get("speaker") or "旁白")[:100], "text": item["text"].strip()[:5000], "emotion": str(item.get("emotion") or "neutral")[:50], "tone_description": str(item.get("tone_description") or "")[:1000]})
    if not sentences:
        raise ValueError("LLM 未提取到可用配音文本")
    return {"characters": response.get("characters") if isinstance(response.get("characters"), list) else [], "sentences": sentences}


def ai_split_chapters(value: str, max_chars: int):
    source = _source_limit(value)
    system_prompt = "你是文本章节规划助手。输出扁平章节，不要树结构。严格返回 JSON：{\"chapters\":[{\"title\":\"章节标题\",\"text\":\"原文片段\"}]}。章节文本只能来自原文，按顺序完整覆盖原文。"
    response = LLMClient().chat("voiceforge_chapter_split", f"每章最多 {max_chars} 字。原文：\n{source}", response_json=True, system_prompt=system_prompt, temperature=0.2)
    items = response.get("chapters") if isinstance(response, dict) else None
    if not isinstance(items, list):
        raise ValueError("LLM 未返回有效章节结果")
    chapters = [{"title": str(item.get("title") or f"章节 {index + 1}")[:200], "text": str(item.get("text") or "").strip()} for index, item in enumerate(items) if isinstance(item, dict) and str(item.get("text") or "").strip()]
    if not chapters or normalize_text("".join(item["text"] for item in chapters)) != normalize_text(source):
        raise ValueError("LLM 分章结果与原文不一致")
    return chapters
