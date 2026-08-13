export function toJsonEvent(event) {
    if (event.type !== "message_update") {
        return event;
    }
    const assistantMessageEvent = event.assistantMessageEvent;
    if (!("partial" in assistantMessageEvent)) {
        return { type: "message_update", assistantMessageEvent };
    }
    const { partial: _partial, ...deltaEvent } = assistantMessageEvent;
    return { type: "message_update", assistantMessageEvent: deltaEvent };
}
//# sourceMappingURL=json-event.js.map