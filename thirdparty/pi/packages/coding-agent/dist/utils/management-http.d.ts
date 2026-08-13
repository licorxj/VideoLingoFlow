type FetchInput = Parameters<typeof fetch>[0];
export interface FetchRetryOptions {
    /** Number of additional attempts after the initial request. Defaults to two. */
    maxRetries?: number;
    /** Retry transient HTTP responses as well as transport failures. Defaults to true. */
    retryOnStatus?: boolean;
    /** Per-attempt timeout. A new timeout is created for every attempt. */
    timeoutMs?: number;
}
/**
 * Fetch a management HTTP resource with a bounded immediate retry.
 *
 * This is intentionally a transport-level helper for idempotent management
 * requests (version checks, catalogs, and downloads). It must not be used for
 * agent/model operations: those can fail after the HTTP request starts and are
 * retried by their semantic caller instead.
 *
 * Caller cancellation is terminal. When timeoutMs is supplied, it is the
 * overall time budget shared by all attempts.
 */
export declare function fetchWithRetry(input: FetchInput, init?: RequestInit | undefined, options?: FetchRetryOptions): Promise<Response>;
export {};
//# sourceMappingURL=management-http.d.ts.map