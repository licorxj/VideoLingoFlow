import type { FileError, Result } from "../types.ts";
import { type SessionCreateOptions, type SessionMetadata, type SessionRepo } from "./types.ts";
export interface SessionSearchOptions {
    text: string;
    cwd?: string;
}
export interface SessionSearchHit<TMetadata extends SessionMetadata = SessionMetadata> {
    metadata: TMetadata;
    entryId: string;
    timestamp: string;
    snippet?: string;
    score?: number;
}
export interface SessionSearch<TMetadata extends SessionMetadata = SessionMetadata> {
    search(options: SessionSearchOptions): Promise<SessionSearchHit<TMetadata>[]>;
}
export declare function getFileSystemResultOrThrow<TValue>(result: Result<TValue, FileError>, message: string): TValue;
export declare function createScanningSessionSearch<TMetadata extends SessionMetadata, TCreateOptions extends SessionCreateOptions, TListOptions>(source: Pick<SessionRepo<TMetadata, TCreateOptions, TListOptions>, "list" | "open">): SessionSearch<TMetadata>;
//# sourceMappingURL=search.d.ts.map