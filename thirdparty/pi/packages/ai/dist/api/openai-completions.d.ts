import OpenAI from "openai";
import type { ChatCompletionMessageParam } from "openai/resources/chat/completions.js";
import type { Context, Model, OpenAICompletionsCompat, SimpleStreamOptions, StreamFunction, StreamOptions, ThinkingBudgets } from "../types.ts";
export interface OpenAICompletionsOptions extends StreamOptions {
    toolChoice?: OpenAI.Chat.Completions.ChatCompletionToolChoiceOption;
    reasoningEffort?: "minimal" | "low" | "medium" | "high" | "xhigh" | "max";
    /** Token budgets per thinking level. Only used when `compat.supportsThinkingTokenBudget` is set. */
    thinkingBudgets?: ThinkingBudgets;
}
export interface ConvertCompletionsMessagesOptions {
    grammarToolInputProperties?: ReadonlyMap<string, string>;
}
type ResolvedOpenAICompletionsCompat = Omit<Required<OpenAICompletionsCompat>, "cacheControlFormat" | "deferredToolsMode" | "supportsThinkingTokenBudget"> & {
    cacheControlFormat?: OpenAICompletionsCompat["cacheControlFormat"];
    deferredToolsMode?: OpenAICompletionsCompat["deferredToolsMode"];
    supportsThinkingTokenBudget?: OpenAICompletionsCompat["supportsThinkingTokenBudget"];
};
export declare const stream: StreamFunction<"openai-completions", OpenAICompletionsOptions>;
export declare const streamSimple: StreamFunction<"openai-completions", SimpleStreamOptions>;
export declare function convertMessages(model: Model<"openai-completions">, context: Context, compat: ResolvedOpenAICompletionsCompat, options?: ConvertCompletionsMessagesOptions): ChatCompletionMessageParam[];
export {};
//# sourceMappingURL=openai-completions.d.ts.map