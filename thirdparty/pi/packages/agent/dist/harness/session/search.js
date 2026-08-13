import { SessionError } from "./types.js";
export function getFileSystemResultOrThrow(result, message) {
    if (!result.ok) {
        const code = result.error.code === "not_found" ? "not_found" : "storage";
        throw new SessionError(code, `${message}: ${result.error.message}`, result.error);
    }
    return result.value;
}
class ScanningSessionSearch {
    source;
    constructor(source) {
        this.source = source;
    }
    async search(options) {
        const normalizedText = options.text.trim().toLowerCase();
        if (!normalizedText)
            return [];
        const hits = [];
        for (const metadata of await this.source.list()) {
            const cwd = metadata.cwd;
            if (options.cwd !== undefined && cwd !== options.cwd)
                continue;
            const session = await this.source.open(metadata);
            for (const entry of await session.findEntries({ order: "oldestFirst" })) {
                const payload = JSON.stringify(entry);
                if (!payload.toLowerCase().includes(normalizedText))
                    continue;
                hits.push({
                    metadata,
                    entryId: entry.id,
                    timestamp: new Date(entry.timestamp).toISOString(),
                    snippet: payload,
                });
            }
        }
        return hits;
    }
}
export function createScanningSessionSearch(source) {
    return new ScanningSessionSearch(source);
}
//# sourceMappingURL=search.js.map