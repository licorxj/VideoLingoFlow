import type { AgentSessionEvent } from "../core/agent-session.ts";
type WithoutPartial<T> = T extends {
    partial: unknown;
} ? Omit<T, "partial"> : T;
type ToJsonEvent<T> = T extends {
    type: "message_update";
    assistantMessageEvent: infer TAssistantMessageEvent;
} ? {
    type: "message_update";
    assistantMessageEvent: WithoutPartial<TAssistantMessageEvent>;
} : T;
/** Session event shape emitted by the JSON and RPC stdout protocols. */
export type JsonAgentSessionEvent = ToJsonEvent<AgentSessionEvent>;
type MessageUpdateEvent = Extract<AgentSessionEvent, {
    type: "message_update";
}>;
type JsonMessageUpdateEvent = Extract<JsonAgentSessionEvent, {
    type: "message_update";
}>;
/**
 * Remove cumulative assistant snapshots from streaming wire events.
 * `message_start` provides the initial message, deltas build it, and
 * `message_end` provides the final authoritative message.
 */
export declare function toJsonEvent(event: MessageUpdateEvent): JsonMessageUpdateEvent;
export declare function toJsonEvent(event: AgentSessionEvent): JsonAgentSessionEvent;
export {};
//# sourceMappingURL=json-event.d.ts.map