﻿# LocalRouter - Dependencies

## System Requirements

| Requirement | Minimum Version | Recommended Version |
|-------------|-----------------|-------------------|
| Python | 3.10 | 3.12 |
| Node.js | 18 | 20 LTS |
| npm | 9 | 10 |
| pip | 21 | 24 |

---

## Backend Dependencies (Python)

Source: `backend/requirements.txt`

| Package | Version | Purpose |
|---------|---------|---------|
| **fastapi** | 0.115.0 | Web framework for building the REST API |
| **uvicorn[standard]** | 0.30.0 | ASGI server for running FastAPI |
| **sqlalchemy[asyncio]** | 2.0.35 | Async ORM for database operations |
| **aiosqlite** | 0.20.0 | Async SQLite driver |
| **alembic** | 1.13.2 | Database migration support (for future use) |
| **pydantic** | 2.9.0 | Data validation and settings management |
| **pydantic-settings** | 2.5.0 | Environment variable / .env file loading |
| **httpx** | 0.27.0 | Async HTTP client for upstream API forwarding |
| **cryptography** | 43.0.0 | Fernet symmetric encryption for API keys |
| **python-dotenv** | 1.0.1 | .env file loading |

### Backend Dev / Runtime Dependencies

These are included automatically with `uvicorn[standard]`:

- `uvloop` 鈥?Fast event loop (Linux only)
- `httptools` 鈥?Fast HTTP parser
- `websockets` 鈥?WebSocket support (for future features)

---

## Frontend Dependencies (Node.js)

Source: `frontend/package.json`

### Production Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| **react** | ^18.3.1 | UI library |
| **react-dom** | ^18.3.1 | React DOM renderer |
| **react-router-dom** | ^6.26.0 | Client-side routing |
| **@tanstack/react-query** | ^5.56.0 | Server state management / data fetching |
| **axios** | ^1.7.0 | HTTP client for API calls |
| **zustand** | ^4.5.0 | Lightweight client state management |
| **clsx** | ^2.1.0 | Conditional className utility |
| **tailwind-merge** | ^2.5.0 | Tailwind class merging without conflicts |
| **class-variance-authority** | ^0.7.0 | Type-safe component variants |
| **@radix-ui/react-slot** | ^1.1.0 | Radix UI primitive 鈥?Slot |
| **@radix-ui/react-dialog** | ^1.1.0 | Radix UI primitive 鈥?Dialog/Modal |
| **@radix-ui/react-dropdown-menu** | ^2.1.0 | Radix UI primitive 鈥?Dropdown Menu |
| **@radix-ui/react-select** | ^2.1.0 | Radix UI primitive 鈥?Select |
| **@radix-ui/react-switch** | ^1.1.0 | Radix UI primitive 鈥?Switch/Toggle |
| **@radix-ui/react-tabs** | ^1.1.0 | Radix UI primitive 鈥?Tabs |
| **@radix-ui/react-tooltip** | ^1.1.0 | Radix UI primitive 鈥?Tooltip |
| **@radix-ui/react-label** | ^2.1.0 | Radix UI primitive 鈥?Label |
| **@radix-ui/react-separator** | ^1.1.0 | Radix UI primitive 鈥?Separator |
| **lucide-react** | ^0.441.0 | Icon library |
| **recharts** | ^2.13.0 | Charting library (Dashboard) |

### Development Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| **typescript** | ^5.5.0 | TypeScript compiler |
| **vite** | 5.4.11 | Build tool and dev server |
| **@vitejs/plugin-react** | 4.3.1 | Vite React plugin |
| **tailwindcss** | ^3.4.12 | Utility-first CSS framework |
| **postcss** | ^8.4.47 | CSS post-processor |
| **autoprefixer** | ^10.4.20 | CSS vendor prefix auto-adding |
| **@types/react** | ^18.3.0 | React TypeScript types |
| **@types/react-dom** | ^18.3.0 | React DOM TypeScript types |

---

## Dependency Graph

```
LocalRouter
├── Backend (Python 3.10+)
│   ├── fastapi ─── uvicorn ─── httptools
│   │   └── pydantic ─── pydantic-settings ─── python-dotenv
│   ├── sqlalchemy[asyncio] ─── aiosqlite
│   ├── httpx ─── HTTP forwarding
│   └── cryptography ─── Fernet encryption
│
├── Frontend (Node.js 18+)
│   ├── react ─── react-dom ─── react-router-dom
│   ├── @tanstack/react-query ─── axios
│   ├── zustand ─── state management
│   ├── shadcn/ui (Radix primitives + Tailwind)
│   │   └── @radix-ui/* (dialog, select, switch, tabs, etc.)
│   └── vite ─── typescript
│       └── tailwindcss ─── postcss ─── autoprefixer
│
└── Database
    └── SQLite (zero-config, file-based)
```
