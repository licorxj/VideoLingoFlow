"""subtitle_reduction: 调用 LLM 缩减超长句子的朗读文本（共享模块）。

从 s09_tts 的 ``_llm_reduce_subtitles`` 抽取，供 s08_dub_task（语速预测缩减）与
s09_tts（真实时长超槽缩减）复用。

约定：调用方保证每个 seg 携带以下字段：
- ``read_text``: 待缩减的朗读文本
- ``duration``: 目标时间槽时长（秒）
- ``real_duration``: 实际/预测的朗读时长（秒），用于计算目标缩减比例

缩减成功后原地写回：``read_text_original`` 保存原文，``read_text`` 更新为缩减结果。

组装模式（默认）：
    同批的多条句子组装进**一条** LLM 请求，模板 id 为 ``{step_name}_batch``
    （如 ``s09_subtitle_reduction_batch``），请求体为 JSON 数组，返回按 index 回写。
    每句的目标缩减比例不同，故逐句携带 ``max_reduction_pct``。
    若批量模板缺失 / 请求失败 / 返回解析失败，自动降级为该批的逐句请求，保证不丢缩减。
"""

import json
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend.config.config_manager import config

# 批量模板缺失时的内置兜底提示词（仍为组装式，一条请求处理多句）
_BATCH_SYSTEM_PROMPT = (
    "你是一个专业的字幕朗读文本精简专家。请对给定的多条朗读文本逐条精简，"
    "使其适合更快的语音合成。\n\n"
    "## 严格要求\n"
    "1. 仅返回 JSON 对象：{\"segments\": [{\"index\": <原样回填>, \"read_text\": <精简文本>}]}。\n"
    "2. 每条必须保留输入中的 index，且条数与输入一致，不要遗漏、不要新增、不要改变顺序。\n"
    "3. 每条按其自带的 max_reduction_pct 缩短（约缩短到 target_ratio）。\n"
    "4. 仅删除冗余修饰词、填充词、重复表达。\n"
    "5. 保留全部关键信息（数字、日期、专有名词、动作主体）。\n"
    "6. 必须保持完整句子结构，不能变成短语。\n"
    "7. 如果是中文：删除'其实','真的','非常','特别'等填充词。\n"
    "8. 如果是英文：删除冗余冠词，将被动语态改为主动语态。\n"
    "9. 无法在不损伤原意的前提下缩短的句子，原样返回其 read_text。\n"
    "10. 只输出 JSON，不要任何解释、代码块或前后缀。"
)


def _is_short_sentence(text: str) -> bool:
    """短句判定：中文少于 3 字、词类语言少于 2 词 → 不缩减。"""
    try:
        from backend.utils.tts_duration_estimator import is_short_sentence
        return is_short_sentence(text)
    except Exception:
        stripped = str(text or "").strip()
        return len(stripped) < 3


def _target_reduction(seg: dict) -> Tuple[float, int]:
    """计算单句的目标保留比例与最大缩减百分比。"""
    duration = seg.get("duration", 1) or 1
    real_dur = seg.get("real_duration", duration) or duration
    try:
        target_ratio = duration / real_dur if real_dur > 0 else 0.8
    except (TypeError, ValueError):
        target_ratio = 0.8
    target_ratio = max(0.5, target_ratio)
    return target_ratio, max(10, int((1 - target_ratio) * 100))


def _batch_payload(seg: dict, position: int) -> Dict[str, Any]:
    """组装模式下单句的请求载荷（含各自的缩减目标）。"""
    target_ratio, max_reduction_pct = _target_reduction(seg)
    return {
        "index": seg.get("index", position),
        "read_text": str(seg.get("read_text") or ""),
        "target_ratio": f"{target_ratio:.0%}",
        "max_reduction_pct": max_reduction_pct,
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
        print(f"  ⚠ 批量缩减模板读取失败，使用内置提示词: {e}")

    if assembled.get("found"):
        return {
            "system_prompt": assembled.get("system_prompt") or "",
            "user_prompt": assembled.get("user_prompt") or "",
        }

    user_prompt = (
        f"请对以下 {len(payloads)} 条朗读文本逐条精简，每条按其自带的 "
        f"max_reduction_pct 缩短（约缩短到 target_ratio）。\n\n"
        f"【待精简文本】\n{segments_json}\n\n"
        f"【输出】\n"
        '{"segments": [{"index": 0, "read_text": "精简后的文本"}]}'
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


def _apply_update(seg: dict, new_text: str, min_reduction_ratio: float, _log) -> bool:
    """校验并写回单句缩减结果，返回是否应用。"""
    original = str(seg.get("read_text") or "")
    new_text = str(new_text or "").strip().strip('"').strip("'")
    idx = seg.get("index", "?")
    if not new_text or new_text == original:
        return False
    if len(new_text) >= len(original) * min_reduction_ratio:
        _log(f"    [{idx}] 缩减不足({len(new_text)}/{len(original)})，跳过")
        return False
    seg["read_text_original"] = original
    seg["read_text"] = new_text
    _log(f"    [{idx}] 缩减: {original[:40]}... → {new_text[:40]}...")
    return True


def _try_batch_reduce(
    llm,
    batch: List[dict],
    step_name: str,
    min_reduction_ratio: float,
    _log,
) -> Optional[int]:
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
        if _apply_update(seg, new_text, min_reduction_ratio, _log):
            applied += 1
    return applied


def _reduce_one_by_one(
    llm,
    batch: List[dict],
    step_name: str,
    min_reduction_ratio: float,
    _log,
) -> int:
    """降级模式：每句 1 条请求（沿用原逐句实现）。"""
    requests = []
    for seg in batch:
        read_text = seg.get("read_text", "")
        target_ratio, max_reduction_pct = _target_reduction(seg)

        try:
            from backend.prompts.prompt_service import get_prompt_service
            assembled = get_prompt_service().assemble_prompt(step_name, {
                "target_ratio": f"{target_ratio:.0%}",
                "max_reduction_pct": str(max_reduction_pct),
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
                    f"你是一个专业的字幕朗读文本精简专家。请严格缩短以下朗读文本的长度，使其适合更快的语音合成。\n\n"
                    f"【严格要求】\n"
                    f"1. 必须将文本缩短至原文的 {target_ratio:.0%} 左右（即缩短约 {max_reduction_pct}%）\n"
                    f"2. 仅删除冗余修饰词、填充词、重复表达\n"
                    f"3. 保留全部关键信息（数字、日期、专有名词、动作主体）\n"
                    f"4. 必须保持完整句子结构，不能变成短语\n"
                    f"5. 如果是中文：删除'其实','真的','非常','特别',' basically',' literally',' you know',' I mean'等填充词\n"
                    f"6. 如果是英文：删除'article冗余','passive voice改为active'等\n"
                    f"7. 只输出精简后的文本，不要任何解释、引号或前后缀\n\n"
                    f"【原文】\n"
                    f"{read_text}\n\n"
                    f"【精简结果】"
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
            _log(f"  ⚠ LLM 缩减失败: {result['error']}")
            continue
        if _apply_update(seg, result, min_reduction_ratio, _log):
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


def reduce_overflow_texts(
    segs: List[dict],
    step_name: str = "s09_subtitle_reduction",
    skip_short: bool = True,
    min_reduction_ratio: float = 0.9,
    log: Optional[Callable[[str], None]] = None,
    batch_mode: bool = True,
) -> int:
    """调用 LLM 缩减超长句子的朗读文本（默认组装模式），原地写回结果。

    Args:
        segs: 需要缩减的片段列表（字段约定见模块 docstring）
        step_name: LLM 请求步骤名与提示词模板名（批量模板为 ``{step_name}_batch``）
        skip_short: 是否跳过短句（中文<3字 / 英文<2词）
        min_reduction_ratio: 缩减校验阈值，结果长度需低于原文该比例才应用（默认 0.9）
        log: 日志回调（默认 print）
        batch_mode: True=组装模式（每批 1 条请求，失败自动降级逐句）；False=逐句模式

    Returns:
        实际应用缩减的句子数
    """
    _log = log or (lambda msg: print(msg))

    try:
        from backend.llm.llm_client import get_llm_client
        llm = get_llm_client()
    except Exception as e:
        _log(f"  ⚠ LLM 客户端不可用，跳过字幕缩减: {e}")
        return 0

    max_concurrent = int(config.get("llm.max_concurrent") or 10)
    max_request_chars = int(config.get("llm.max_request_chars") or 12000)

    reduce_tasks = []
    for seg in segs:
        read_text = str(seg.get("read_text") or "").strip()
        if not read_text:
            continue
        if skip_short and _is_short_sentence(read_text):
            _log(f"    [{seg.get('index', '?')}] 短句跳过缩减: {read_text}")
            continue
        reduce_tasks.append(seg)

    if not reduce_tasks:
        return 0

    batches = _pack_batches(reduce_tasks, max_request_chars, step_name)
    mode_tip = "组装模式(每批 1 次请求)" if batch_mode else "逐句模式"
    _log(
        f"  - 开始缩减 {len(reduce_tasks)} 段文本 [{mode_tip}, "
        f"并发={max_concurrent}, 批次字数限制={max_request_chars}]"
    )
    _log(f"  - 分为 {len(batches)} 个批次处理")

    reduced_count = 0
    fallback_batches = 0
    for batch_idx, batch in enumerate(batches):
        applied: Optional[int] = None
        if batch_mode:
            applied = _try_batch_reduce(llm, batch, step_name, min_reduction_ratio, _log)
            if applied is None:
                fallback_batches += 1
                _log(f"  ⚠ 批次 {batch_idx + 1} 组装请求失败，降级为逐句请求")
        if applied is None:
            applied = _reduce_one_by_one(llm, batch, step_name, min_reduction_ratio, _log)
        reduced_count += applied

    if batch_mode and fallback_batches:
        _log(f"  - 组装模式降级 {fallback_batches}/{len(batches)} 批")

    return reduced_count
