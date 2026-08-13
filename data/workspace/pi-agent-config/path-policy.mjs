import path from "node:path";

const policy = JSON.parse(process.env.VIDEOLINGO_PI_PATH_POLICY || "{}");
const readBlacklist = Array.isArray(policy.read_blacklist) ? policy.read_blacklist : [];
const writeBlacklist = Array.isArray(policy.write_blacklist) ? policy.write_blacklist : [];

const overlaps = (candidate, blocked) => {
  const relative = path.relative(blocked, candidate);
  const inverse = path.relative(candidate, blocked);
  return relative === "" || inverse === "" || (!relative.startsWith("..") && !path.isAbsolute(relative)) || (!inverse.startsWith("..") && !path.isAbsolute(inverse));
};

const blocked = (input, blacklist, cwd) => {
  if (typeof input !== "string" || !input.trim()) return false;
  const candidate = path.resolve(cwd, input);
  return blacklist.some((item) => overlaps(candidate, item));
};

export default function (pi) {
  pi.on("tool_call", (event, ctx) => {
    if (event.toolName === "bash") {
      return { block: true, reason: "Bash is disabled because path-level permissions cannot be enforced safely for shell commands." };
    }
    const isWrite = event.toolName === "write" || event.toolName === "edit";
    const isRead = event.toolName === "read" || event.toolName === "ls" || event.toolName === "grep" || event.toolName === "find";
    if (!isWrite && !isRead) return undefined;
    const requestedPath = typeof event.input?.path === "string" ? event.input.path : ".";
    const blacklist = isWrite ? writeBlacklist : readBlacklist;
    if (blocked(requestedPath, blacklist, ctx.cwd)) {
      return { block: true, reason: `${isWrite ? "Write" : "Read"} access is blocked for this path by the Agent permission policy.` };
    }
    return undefined;
  });
}
