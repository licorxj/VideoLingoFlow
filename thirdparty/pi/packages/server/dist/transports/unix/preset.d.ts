import { PiServer } from "../../server.ts";
import type { PiServerService } from "../../types.ts";
import type { UnixServerOptions } from "./types.ts";
/** Compose PiServer with one Unix-domain socket listener. */
export declare function createUnixServer(service: PiServerService, options: UnixServerOptions): PiServer;
//# sourceMappingURL=preset.d.ts.map