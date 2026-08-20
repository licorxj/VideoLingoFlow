# VideoLingoFlow Agent Knowledge

This directory contains the English knowledge documents loaded by the 小π Agent.

## Path Resolution

`PROJECT_ROOT` means the absolute root directory of the running VideoLingoFlow checkout. In the local installation it is `Y:\VideoLingoLc`.

Every relative path in these documents is relative to `PROJECT_ROOT`, never to the Pi process working directory. Resolve a relative path by joining it to `PROJECT_ROOT` before reading or modifying it.

Examples:

- `backend/main.py` resolves to `PROJECT_ROOT/backend/main.py`.
- `.runtime/local_env.bat` resolves to `PROJECT_ROOT/.runtime/local_env.bat`.
- `data/workspace` resolves to `PROJECT_ROOT/data/workspace`.

Do not infer a different root from a session directory or a temporary working directory.

## Document Index

- `persona.md`: reference copy of the built-in global persona (fixed in `backend/pi_rpc/manager.py`, not editable).
- `project-architecture.md`: repository architecture, runtime services, and technology stack.
- `backend-api-catalog.md`: non-authentication and non-billing backend API groups.
- `skills-index.md`: project workflow capabilities and the source paths for their implementations.
- `docs/capability-index.md`: capability document index used by the general assistant (read on demand).
- `docs/*.md`: role capability documents (node creation, workflow orchestration, task execution, file management, publishing).

The Pi manager loads selected base documents at session creation. Changing a document affects newly created sessions. Role capability documents are selected per assistant in the 小π Agent settings.
