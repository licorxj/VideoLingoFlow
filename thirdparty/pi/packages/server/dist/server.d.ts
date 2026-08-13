import { type ByteConnection, type ByteConnectionHandler } from "./connection.ts";
import type { PiServerOptions, PiServerService } from "./types.ts";
export declare class PiServer {
    readonly id: string;
    private readonly listeners;
    private readonly maxFrameLength;
    private readonly handshakeTimeoutMs;
    private readonly onError;
    private readonly connections;
    private readonly sessions;
    private readonly snapshots;
    private closing;
    private closePromise?;
    private startPromise?;
    private started;
    constructor(service: PiServerService, options: PiServerOptions);
    get addresses(): readonly string[];
    start(): Promise<this>;
    private startInternal;
    accept(connection: ByteConnection): ByteConnectionHandler;
    close(): Promise<void>;
    private closeInternal;
    private receive;
    private dispatchMessage;
    private finishHandshake;
    private handleRequest;
    private transportClosed;
    private disconnect;
    private sendMessage;
    private failProtocol;
    private closeServerState;
    private closeConnection;
    private toProtocolError;
    private reportError;
}
//# sourceMappingURL=server.d.ts.map