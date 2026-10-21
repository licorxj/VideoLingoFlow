import { VoiceForgeEmotionSuggestion, voiceForgeApi } from "@/api/voiceforge";

/**
 * 单次 LLM 填充请求的情绪数量上限（与后端 VoiceEmotionLlmFillRequest.emotions 一致）。
 * 超过该数量时前端自动分块逐块请求，避免：
 * 1. 触发后端参数校验 422（如全选 36 个情绪标签）；
 * 2. 单次 LLM 返回过大 JSON 导致截断或丢项。
 */
export const EMOTION_FILL_CHUNK = 20;

/**
 * 分块请求 LLM 填充情绪文本与指令，合并返回全部建议。
 * 任一块失败即整体抛出，由调用方展示错误。
 */
export async function fillEmotionSuggestions(
  voiceId: string,
  emotions: string[],
  characterBackground: string,
  interfaceId: string,
): Promise<VoiceForgeEmotionSuggestion[]> {
  const suggestions: VoiceForgeEmotionSuggestion[] = [];
  for (let index = 0; index < emotions.length; index += EMOTION_FILL_CHUNK) {
    const chunk = emotions.slice(index, index + EMOTION_FILL_CHUNK);
    const result = await voiceForgeApi.fillVoiceEmotions(voiceId, {
      emotions: chunk,
      character_background: characterBackground,
      interface_id: interfaceId,
    });
    suggestions.push(...(result.data.tasks || []));
  }
  return suggestions;
}

/** 把 pydantic 422 的 too_long 校验信息翻译为可读中文 */
export function friendlyValidationMessage(item: any, fallback: string): string {
  if (typeof item === "string") return item;
  if (item && typeof item === "object") {
    if (item.type === "too_long" && item.ctx && typeof item.ctx.max_length === "number") {
      return `最多支持 ${item.ctx.max_length} 项`;
    }
    return item.msg || fallback;
  }
  return fallback;
}
