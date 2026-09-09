"""subtitle_reduction: 调用 LLM 缩减超长句子的朗读文本（共享模块）。

从 s09_tts 的 ``_llm_reduce_subtitles`` 抽取，供 s08_dub_task（语速预测缩减）与
s09_tts（真实时长超槽缩减）复用。

约定：调用方保证每个 seg 携带以下字段：
- ``read_text``: 待缩减的朗读文本
- ``duration``: 目标时间槽时长（秒）
- ``real_duration``: 实际/预测的朗读时长（秒），用于计算目标缩减比例

缩减成功后原地写回：``read_text_original`` 保存原文，``read_text`` 更新为缩减结果。
"""

import traceback
from typing import Callable, List, Optional

from backend.config.config_manager import config


def _is_short_sentence(text: str) -> bool:
    """短句判定：中文少于 3 字、词类语言少于 2 词 → 不缩减。"""
    try:
        from backend.utils.tts_duration_estimator import is_short_sentence
        return is_short_sentence(text)
    except Exception:
        stripped = str(text or "").strip()
        return len(stripped) < 3


def reduce_overflow_texts(
    segs: List[dict],
    step_name: str = "s09_subtitle_reduction",
    skip_short: bool = True,
    min_reduction_ratio: float = 0.9,
    log: Optional[Callable[[str], None]] = None,
) -> int:
    """调用 LLM 缩减超长句子的朗读文本（批次并发），原地写回结果。

    Args:
        segs: 需要缩减的片段列表（字段约定见模块 docstring）
        step_name: LLM 请求与提示词模板名（如 "s09_subtitle_reduction"）
        skip_short: 是否跳过短句（中文<3字 / 英文<2词）
        min_reduction_ratio: 缩减校验阈值，结果长度需低于原文该比例才应用（默认 0.9）
        log: 日志回调（默认 print）

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

    _log(f"  - 开始批次缩减 {len(reduce_tasks)} 段文本 (并发={max_concurrent}, 批次字数限制={max_request_chars})")

    # 打包批次：每批字符数不超过 max_request_chars
    batches = []
    current_batch = []
    current_chars = 0
    for seg in reduce_tasks:
        text_len = len(seg.get("read_text", ""))
        if current_batch and current_chars + text_len > max_request_chars:
            batches.append(current_batch)
            current_batch = []
            current_chars = 0
        current_batch.append(seg)
        current_chars += text_len
    if current_batch:
        batches.append(current_batch)

    _log(f"  - 分为 {len(batches)} 个批次处理")

    reduced_count = 0
    for batch_idx, batch in enumerate(batches):
        requests = []
        for seg in batch:
            read_text = seg.get("read_text", "")
            duration = seg.get("duration", 1) or 1
            real_dur = seg.get("real_duration", duration) or duration
            try:
                target_ratio = duration / real_dur if real_dur > 0 else 0.8
            except (TypeError, ValueError):
                target_ratio = 0.8
            target_ratio = max(0.5, target_ratio)
            max_reduction_pct = max(10, int((1 - target_ratio) * 100))

            # Try to use JSON template via prompt service
            from backend.prompts.prompt_service import get_prompt_service
            svc = get_prompt_service()
            assembled = svc.assemble_prompt(step_name, {
                "target_ratio": f"{target_ratio:.0%}",
                "max_reduction_pct": str(max_reduction_pct),
                "read_text": read_text,
            })

            if assembled.get("found"):
                prompt_data = {
                    "user_prompt": assembled["user_prompt"],
                    "system_prompt": assembled.get("system_prompt") or "",
                }
            else:
                # Fallback to hardcoded prompt
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

        # 并发执行批次请求
        try:
            results = llm.batch_chat(requests, max_workers=max_concurrent)

            for seg, result in zip(batch, results):
                read_text = seg.get("read_text", "")

                if not result or not isinstance(result, str):
                    continue
                if isinstance(result, dict) and "error" in result:
                    _log(f"  ⚠ LLM 缩减失败: {result['error']}")
                    continue

                result = result.strip().strip('"').strip("'")
                # 后处理校验：必须确实缩短了文本（至少缩短 min_reduction_ratio 比例）
                if result and result != read_text and len(result) < len(read_text) * min_reduction_ratio:
                    seg["read_text_original"] = read_text
                    seg["read_text"] = result
                    reduced_count += 1
                    idx = seg.get("index", "?")
                    _log(f"    [{idx}] 缩减: {read_text[:40]}... → {result[:40]}...")
                elif result and result != read_text:
                    idx = seg.get("index", "?")
                    _log(f"    [{idx}] 缩减不足({len(result)}/{len(read_text)})，跳过")
        except Exception as e:
            _log(f"  ⚠ 批次 {batch_idx + 1} 处理异常: {e}")
            traceback.print_exc()

    return reduced_count
