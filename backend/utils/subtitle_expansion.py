"""subtitle_expansion: 调用 LLM 丰富偏短朗读文本的字数（共享模块）。

与 ``subtitle_reduction`` 相反：当 TTS 音频明显短于时间槽（偏慢/偏短）、
减速填充已到节点「最慢值」仍填不满槽位时，通过 LLM 在不改变原意的前提下
补充自然的口语细节，把朗读文本加长到估算的「期望字数」，使重新配音后的音频
更贴近时间槽，避免留下长静音。

约定：调用方保证每个 seg 携带以下字段：
- ``read_text``: 待丰富的朗读文本
- ``duration``: 目标时间槽时长（秒）
- ``real_duration``: 实际朗读时长（秒）

丰富成功后原地写回：``read_text_original`` 保存原文，``read_text`` 更新为丰富结果，
并置 ``read_text_expanded = True``（供调用方识别，同时避免多轮重复丰富）。

组装模式（默认）：
    同批的多条句子组装进**一条** LLM 请求，模板 id 为 ``{step_name}_batch``
    （如 ``s09_subtitle_expansion_batch``），请求体为 JSON 数组，返回按 index 回写。
    每条自带 ``target_units``（期望字数）与 ``unit_name``（单位名）。
    若批量模板缺失 / 请求失败 / 返回解析失败，自动降级为该批的逐句请求。
"""

import json
import traceback
from typing import Any, Callable, Dict, List, Optional

from backend.config.config_manager import config

# 丰富结果的允许增长上限（相对目标字数/原字数的较大者），避免反而溢出时间槽
_MAX_GROWTH = 1.35

# 批量模板缺失时的内置兜底提示词（组装式，一条请求处理多句）
_BATCH_SYSTEM_PROMPT = (
    "你是一个专业的影视字幕本地化编辑，擅长在不改变原意的前提下，为偏短的台词"
    "补充自然、口语化的细节，使其朗读时长更贴近目标时间槽。\n\n"
    "## 严格要求\n"
    "1. 仅返回 JSON 对象：{\"segments\": [{\"index\": <原样回填>, \"read_text\": <丰富后的文本>}]}。\n"
    "2. 每条必须保留输入中的 index，且条数与输入一致，不要遗漏、不要新增、不要改变顺序。\n"
    "3. 以每条自带的 target_units 为目标长度（单位见 unit_name），尽量接近该字数。\n"
    "4. 只做无损丰富：补充语气词/连接词、对已有信息的同义展开、自然的限定与递进；"
    "严禁新增数字、日期、专有名词、人物或任何原句没有的事实信息。\n"
    "5. 保持原句的语义、人称、时态与情感色彩不变，必须是完整通顺的句子。\n"
    "6. 不要在结果里保留 target_units/unit_name 等字段，只输出 read_text。\n"
    "7. 若原句已经接近或超过 target_units，原样返回其 read_text。\n"
    "8. 只输出 JSON，不要任何解释、代码块或前后缀。"
)


def _unit_count(text: str) -> int:
    """统计文本的朗读单元数（汉字/假名/单词等），失败时退回字符数。"""
    try:
        from backend.utils.tts_duration_estimator import count_speak_units
        return count_speak_units(text)
    except Exception:
        return len(str(text or "").strip())


def _target_units_for(seg: dict) -> tuple:
    """计算单句的期望字数与单元名称。"""
    try:
        from backend.utils.tts_duration_estimator import estimate_target_units
        return estimate_target_units(
            seg.get("duration", 0), str(seg.get("read_text") or "")
        )
    except Exception:
        duration = seg.get("duration", 0) or 0
        return max(1, int(duration * 4)), "字符"


def _batch_payload(seg: dict, position: int) -> Dict[str, Any]:
    """组装模式下单句的请求载荷（含期望字数）。"""
    target_units, unit_name = _target_units_for(seg)
    read_text = str(seg.get("read_text") or "")
    return {
        "index": seg.get("index", position),
        "read_text": read_text,
        "current_units": _unit_count(read_text),
        "target_units": target_units,
        "unit_name": unit_name,
        "slot_seconds": round(float(seg.get("duration", 0) or 0), 2),
        "spoken_seconds": round(float(seg.get("real_duration", 0) or 0), 2),
    }


def _build_batch_prompt(payloads: List[Dict[str, Any]], step_name: str) -> Dict[str, str]:
    """构建组装模式提示词：优先用 ``{step_name}_batch`` 模板，缺失时用内置兜底。"""
    segments_json = json.dumps(payloads, ensure_ascii=False, indent=2)
    try:
        from backend.prompts.prompt_service import get_prompt_service
        assembled = get_prompt_service().assemble_prompt(f"{step_name}_batch", {
            "segments": segments_json,
            "raw_segments": payloads,
            "count": len(payloads),
        })
    except Exception as e:
        assembled = {"found": False}
        print(f"  ⚠ 批量丰富模板读取失败，使用内置提示词: {e}")

    if assembled.get("found"):
        return {
            "system_prompt": assembled.get("system_prompt") or "",
            "user_prompt": assembled.get("user_prompt") or "",
        }

    user_prompt = (
        f"请对以下 {len(payloads)} 条偏短的朗读文本逐条做无损丰富，"
        f"使其朗读字数尽量接近各自自带的 target_units（单位见 unit_name）。\n"
        f"只补语气、修饰与同义展开，严禁新增任何原句没有的事实信息。\n\n"
        f"【待丰富文本】\n{segments_json}\n\n"
        f"【输出】\n"
        '{"segments": [{"index": 0, "read_text": "丰富后的文本"}]}'
    )
    return {"system_prompt": _BATCH_SYSTEM_PROMPT, "user_prompt": user_prompt}


def _coerce_segments(result: Any) -> Optional[List[Any]]:
    """把 LLM 返回规整为 segments 列表，无法解析时返回 None。"""
    if isinstance(result, str):
        text = result.strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
        try:
            result = json.loads(text)
        except Exception:
            return None

    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        for key in ("segments", "data", "results"):
            value = result.get(key)
            if isinstance(value, list):
                return value
    return None


def _apply_expand(seg: dict, new_text: str, _log) -> bool:
    """校验并写回单句丰富结果，返回是否应用。"""
    original = str(seg.get("read_text") or "")
    new_text = str(new_text or "").strip().strip('"').strip("'")
    idx = seg.get("index", "?")
    if not new_text or new_text == original:
        return False

    orig_units = _unit_count(original)
    new_units = _unit_count(new_text)
    target_units, unit_name = _target_units_for(seg)

    # 必须确实变长，否则丰富无意义
    if new_units <= orig_units:
        _log(f"    [{idx}] 丰富后字数未增加({new_units}/{orig_units})，跳过")
        return False
    # 不得超出目标/原字数过多，避免反而溢出时间槽
    cap = max(target_units, orig_units) * _MAX_GROWTH
    if new_units > cap:
        _log(f"    [{idx}] 丰富后字数超上限({new_units}>{int(cap)} {unit_name})，跳过")
        return False

    seg["read_text_original"] = original
    seg["read_text"] = new_text
    seg["read_text_expanded"] = True
    _log(f"    [{idx}] 丰富字数: {orig_units} → {new_units} {unit_name}（目标 {target_units}）")
    return True


def _try_batch_expand(llm, batch: List[dict], step_name: str, _log) -> Optional[int]:
    """组装模式：整批句子 -> 1 条请求。返回应用句数；None 表示需要降级。"""
    payloads = [_batch_payload(seg, i) for i, seg in enumerate(batch)]
    prompt_data = _build_batch_prompt(payloads, step_name)

    try:
        results = llm.batch_chat(
            [{
                # step_name 仍用原名，保证 step_models 模型映射与请求日志一致
                "step_name": step_name,
                "prompt": prompt_data["user_prompt"],
                "system_prompt": prompt_data["system_prompt"],
                "response_json": True,
                "log": True,
            }],
            max_workers=1,
        )
    except Exception as e:
        _log(f"  ⚠ 组装请求异常: {e}")
        traceback.print_exc()
        return None

    result = results[0] if results else None
    if result is None:
        _log("  ⚠ 组装请求无返回")
        return None
    if isinstance(result, dict) and result.get("error"):
        _log(f"  ⚠ 组装请求失败: {result['error']}")
        return None

    items = _coerce_segments(result)
    if items is None:
        _log("  ⚠ 组装请求返回无法解析为 segments 列表")
        return None

    by_index: Dict[Any, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        key = item.get("index")
        text = item.get("read_text") or item.get("text")
        if key is None or not text:
            continue
        by_index[str(key)] = str(text)

    applied = 0
    for position, seg in enumerate(batch):
        key = seg.get("index", position)
        new_text = by_index.get(str(key))
        if not new_text:
            _log(f"    [{key}] 组装结果中缺少该句，跳过")
            continue
        if _apply_expand(seg, new_text, _log):
            applied += 1
    return applied


def _expand_one_by_one(llm, batch: List[dict], step_name: str, _log) -> int:
    """降级模式：每句 1 条请求。"""
    requests = []
    for seg in batch:
        read_text = str(seg.get("read_text") or "")
        target_units, unit_name = _target_units_for(seg)
        current_units = _unit_count(read_text)

        try:
            from backend.prompts.prompt_service import get_prompt_service
            assembled = get_prompt_service().assemble_prompt(step_name, {
                "target_units": str(target_units),
                "unit_name": unit_name,
                "current_units": str(current_units),
                "read_text": read_text,
            })
        except Exception:
            assembled = {"found": False}

        if assembled.get("found"):
            prompt_data = {
                "user_prompt": assembled["user_prompt"],
                "system_prompt": assembled.get("system_prompt") or "",
            }
        else:
            prompt_data = {
                "user_prompt": (
                    f"你是一个专业的影视字幕本地化编辑。请在不改变原意的前提下，"
                    f"把下面这句偏短的台词做无损丰富，使其朗读字数尽量接近 "
                    f"{target_units} {unit_name}（当前 {current_units}）。\n\n"
                    f"【要求】\n"
                    f"1. 只补充语气词、连接词、对已有信息的同义展开\n"
                    f"2. 严禁新增数字、日期、专有名词、人物或任何原句没有的事实\n"
                    f"3. 保持语义、人称、时态、情感不变，必须是完整通顺的一句话\n"
                    f"4. 只输出丰富后的文本，不要任何解释、引号或前后缀\n\n"
                    f"【原句】\n{read_text}\n\n"
                    f"【丰富结果】"
                ),
                "system_prompt": "",
            }

        requests.append({
            "step_name": step_name,
            "prompt": prompt_data["user_prompt"],
            "system_prompt": prompt_data["system_prompt"],
            "response_json": False,
        })

    results = llm.batch_chat(requests, max_workers=int(config.get("llm.max_concurrent") or 10))

    applied = 0
    for seg, result in zip(batch, results):
        if not result or not isinstance(result, str):
            continue
        if isinstance(result, dict) and "error" in result:
            _log(f"  ⚠ LLM 丰富失败: {result['error']}")
            continue
        if _apply_expand(seg, result, _log):
            applied += 1
    return applied


def _pack_batches(tasks: List[dict], max_request_chars: int, step_name: str) -> List[List[dict]]:
    """按字符预算打包批次（组装模式下 1 批 = 1 条请求）。"""
    overhead_prompt = _build_batch_prompt([], step_name)
    overhead = len(overhead_prompt["user_prompt"]) + len(overhead_prompt["system_prompt"])
    budget = max(600, max_request_chars - overhead - 200)

    batches: List[List[dict]] = []
    current_batch: List[dict] = []
    current_chars = 0
    for position, seg in enumerate(tasks):
        seg_chars = len(json.dumps(_batch_payload(seg, position), ensure_ascii=False))
        if current_batch and current_chars + seg_chars > budget:
            batches.append(current_batch)
            current_batch = []
            current_chars = 0
        current_batch.append(seg)
        current_chars += seg_chars
    if current_batch:
        batches.append(current_batch)
    return batches


def expand_short_texts(
    segs: List[dict],
    step_name: str = "s09_subtitle_expansion",
    log: Optional[Callable[[str], None]] = None,
    batch_mode: bool = True,
) -> int:
    """调用 LLM 丰富偏短句子的朗读文本（默认组装模式，一行请求处理多句），原地写回。

    Args:
        segs: 需要丰富的片段列表（字段约定见模块 docstring）
        step_name: LLM 请求步骤名与提示词模板名（批量模板为 ``{step_name}_batch``）
        log: 日志回调（默认 print）
        batch_mode: True=组装模式（每批 1 条请求，失败自动降级逐句）；False=逐句模式

    Returns:
        实际应用丰富的句子数
    """
    _log = log or (lambda msg: print(msg))

    try:
        from backend.llm.llm_client import get_llm_client
        llm = get_llm_client()
    except Exception as e:
        _log(f"  ⚠ LLM 客户端不可用，跳过字幕丰富: {e}")
        return 0

    max_concurrent = int(config.get("llm.max_concurrent") or 10)
    max_request_chars = int(config.get("llm.max_request_chars") or 12000)

    expand_tasks = []
    for seg in segs:
        read_text = str(seg.get("read_text") or "").strip()
        if not read_text:
            continue
        if seg.get("read_text_expanded"):
            _log(f"    [{seg.get('index', '?')}] 已丰富过，跳过")
            continue
        target_units, _unit_name = _target_units_for(seg)
        if target_units <= _unit_count(read_text):
            _log(f"    [{seg.get('index', '?')}] 现有字数已达目标({target_units})，跳过")
            continue
        expand_tasks.append(seg)

    if not expand_tasks:
        return 0

    batches = _pack_batches(expand_tasks, max_request_chars, step_name)
    mode_tip = "组装模式(每批 1 次请求)" if batch_mode else "逐句模式"
    _log(
        f"  - 开始丰富 {len(expand_tasks)} 段文本 [{mode_tip}, "
        f"并发={max_concurrent}, 批次字数限制={max_request_chars}]"
    )
    _log(f"  - 分为 {len(batches)} 个批次处理")

    expanded_count = 0
    fallback_batches = 0
    for batch_idx, batch in enumerate(batches):
        applied: Optional[int] = None
        if batch_mode:
            applied = _try_batch_expand(llm, batch, step_name, _log)
            if applied is None:
                fallback_batches += 1
                _log(f"  ⚠ 批次 {batch_idx + 1} 组装请求失败，降级为逐句请求")
        if applied is None:
            applied = _expand_one_by_one(llm, batch, step_name, _log)
        expanded_count += applied

    if batch_mode and fallback_batches:
        _log(f"  - 组装模式降级 {fallback_batches}/{len(batches)} 批")

    return expanded_count
