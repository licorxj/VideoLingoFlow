import type { JsonValue, ProtocolErrorCode } from "@earendil-works/pi-protocol";
export type PiServerOperationErrorCode = Extract<ProtocolErrorCode, "busy" | "session_locked" | "not_found" | "invalid_request" | "not_implemented">;
export declare const INTERNAL_SERVER_ERROR_MESSAGE = "Internal server error";
export declare const NOT_IMPLEMENTED_MESSAGE = "Operation is not implemented";
/** A service/runtime error that can safely cross the protocol boundary. */
export declare class PiServerError extends Error {
    readonly code: PiServerOperationErrorCode;
    readonly details: JsonValue | undefined;
    constructor(code: PiServerOperationErrorCode, message: string, details?: JsonValue);
}
export declare class SessionBusyError extends PiServerError {
    constructor(message?: string, details?: JsonValue);
}
export declare class SessionLockedError extends PiServerError {
    constructor(message?: string, details?: JsonValue);
}
export declare class SessionNotFoundError extends PiServerError {
    constructor(message?: string, details?: JsonValue);
}
export declare class NotImplementedError extends PiServerError {
    constructor();
}
/** An unsafe failure whose cause is retained for reporting but never serialized. */
export declare class InternalServerError extends Error {
    constructor(cause: unknown);
}
//# sourceMappingURL=errors.d.ts.map