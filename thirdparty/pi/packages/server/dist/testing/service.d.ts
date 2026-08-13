import type { ModelMetadata, ModelRef, SessionMetadata, SessionPhase, SessionSnapshot, ThinkingLevel, TranscriptProgress } from "@earendil-works/pi-protocol";
import { PiServerError } from "../errors.ts";
import type { CreateSessionOptions, PiServerService, PiSessionRuntime, PiSessionRuntimeEvent, PromptInput } from "../types.ts";
export declare const TEST_MODEL: ModelMetadata;
export declare class Deferred<T> {
    readonly promise: Promise<T>;
    private resolvePromise;
    constructor();
    resolve(value: T): void;
}
interface StoredSession {
    snapshot: SessionSnapshot;
}
export declare class TestSessionRuntime implements PiSessionRuntime {
    readonly disposed: Deferred<void>;
    disposeCount: number;
    readonly steers: PromptInput[];
    private readonly stored;
    private readonly onDispose;
    private readonly listeners;
    private pendingPrompt?;
    constructor(stored: StoredSession, onDispose: () => void);
    snapshot(): SessionSnapshot;
    getPhase(): SessionPhase;
    prompt(input: PromptInput): Promise<void>;
    steer(input: PromptInput): Promise<void>;
    abort(): Promise<void>;
    setModel(model: ModelRef): Promise<void>;
    setThinking(thinkingLevel: ThinkingLevel): Promise<void>;
    subscribe(listener: (event: PiSessionRuntimeEvent) => void): () => void;
    dispose(): Promise<void>;
    setPhase(phase: SessionPhase): void;
    finishPrompt(): void;
    emitProgress(progress: TranscriptProgress): void;
    emitError(error: PiServerError): void;
    emitSnapshot(): void;
    private update;
}
interface ListDelay {
    entered: Deferred<void>;
    release: Deferred<void>;
}
export declare class TestServerService implements PiServerService {
    readonly sessions: Map<string, StoredSession>;
    readonly runtimes: Map<string, TestSessionRuntime[]>;
    readonly locked: Set<string>;
    lastCreatedId?: string;
    private nextListDelay?;
    listSessions(): Promise<SessionMetadata[]>;
    listModels(): Promise<ModelMetadata[]>;
    createSession(options: CreateSessionOptions): Promise<PiSessionRuntime>;
    openSession(sessionId: string): Promise<PiSessionRuntime>;
    seed(id?: string, name?: string, cwd?: string, model?: ModelRef, thinkingLevel?: ThinkingLevel): void;
    delayNextList(): ListDelay;
    latestRuntime(id: string): TestSessionRuntime;
    private acquire;
}
export {};
//# sourceMappingURL=service.d.ts.map