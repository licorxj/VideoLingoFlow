import { PiServer } from "../server.js";
import { TestServerService } from "./service.js";
/** Create an unstarted PiServer with deterministic defaults for transport conformance tests. */
export function createTestServer(options) {
    const service = options.service ?? new TestServerService();
    return {
        server: new PiServer(service, {
            listeners: options.listeners,
            maxFrameLength: options.maxFrameLength,
            handshakeTimeoutMs: options.handshakeTimeoutMs,
            serverId: options.serverId,
            onError: options.onError,
        }),
        service,
    };
}
//# sourceMappingURL=server.js.map