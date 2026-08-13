import { PiServer } from "../server.ts";
import type { PiServerOptions, PiServerService } from "../types.ts";
export interface TestServerOptions extends PiServerOptions {
    service?: PiServerService;
}
export interface TestServer {
    server: PiServer;
    service: PiServerService;
}
/** Create an unstarted PiServer with deterministic defaults for transport conformance tests. */
export declare function createTestServer(options: TestServerOptions): TestServer;
//# sourceMappingURL=server.d.ts.map