export const INTERNAL_SERVER_ERROR_MESSAGE = "Internal server error";
export const NOT_IMPLEMENTED_MESSAGE = "Operation is not implemented";
/** A service/runtime error that can safely cross the protocol boundary. */
export class PiServerError extends Error {
    code;
    details;
    constructor(code, message, details) {
        super(message);
        this.name = "PiServerError";
        this.code = code;
        this.details = details;
    }
}
export class SessionBusyError extends PiServerError {
    constructor(message = "Session is busy", details) {
        super("busy", message, details);
        this.name = "SessionBusyError";
    }
}
export class SessionLockedError extends PiServerError {
    constructor(message = "Session is locked", details) {
        super("session_locked", message, details);
        this.name = "SessionLockedError";
    }
}
export class SessionNotFoundError extends PiServerError {
    constructor(message = "Session was not found", details) {
        super("not_found", message, details);
        this.name = "SessionNotFoundError";
    }
}
export class NotImplementedError extends PiServerError {
    constructor() {
        super("not_implemented", NOT_IMPLEMENTED_MESSAGE);
        this.name = "NotImplementedError";
    }
}
/** An unsafe failure whose cause is retained for reporting but never serialized. */
export class InternalServerError extends Error {
    constructor(cause) {
        super(INTERNAL_SERVER_ERROR_MESSAGE, { cause });
        this.name = "InternalServerError";
    }
}
//# sourceMappingURL=errors.js.map