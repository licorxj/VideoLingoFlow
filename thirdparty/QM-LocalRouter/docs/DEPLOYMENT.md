﻿﻿﻿# LocalRouter - Deployment Guide

This guide covers deploying LocalRouter on various platforms.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start (Local)](#quick-start-local)
3. [Docker Deployment](#docker-deployment)
4. [Linux Deployment (Production)](#linux-deployment-production)
5. [Windows Deployment](#windows-deployment)
6. [macOS Deployment](#macos-deployment)
7. [VPS Production Deployment](#vps-production-deployment)
8. [Kubernetes Deployment](#kubernetes-deployment)

---

## Prerequisites

All deployment modes require:

| Requirement | Version | Check |
|-------------|---------|-------|
| Python | 3.10+ | `python --version` |
| Node.js | 18+ | `node --version` |
| npm | 9+ | `npm --version` |

For Docker deployment, only Docker is needed.

---

## Quick Start (Local)

### Step 1: Clone

```bash
git clone https://github.com/licorxj/QM-LocalRouter.git
cd ApiRouteManeger
```

### Step 2: Initialize Database

```bash
cd scripts
python init_db.py        # Cross-platform
# or: ./init_db.sh       # Linux/macOS
# or: init_db.bat        # Windows
cd ..
```

This script will:
- Create a Python virtual environment
- Install backend dependencies
- Create `.env` with default values
- Initialize the SQLite database

### Step 3: Start Services

**Option A 鈥?Management script (recommended):**

```bash
# Linux/macOS
chmod +x scripts/manage.sh
./scripts/manage.sh start

# Windows
scripts\manage.bat start
```

**Option B 鈥?Manual:**

```bash
# Terminal 1: Backend
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 12002

# Terminal 2: Frontend
cd frontend
npm install
npm run dev
```

### Step 4: Access

- **Frontend**: http://localhost:12001
- **Backend Docs**: http://localhost:12002/docs

---

## Docker Deployment

### Using Docker Compose (Recommended)

```bash
# Start services
docker compose up -d

# View logs
docker compose logs -f

# Stop services
docker compose down
```

### Using Docker Directly

```bash
# Build the image
docker build -t localrouter .

# Run the container
docker run -d \
  --name localrouter \
  -p 12002:12002 \
  -p 12001:12001 \
  -v localrouter_data:/app/backend/data \
  --restart unless-stopped \
  localrouter
```

### Docker Persistence

The SQLite database is stored in a Docker volume (`localrouter_data`). To back it up:

```bash
# Create a backup from the running container
docker exec localrouter python -c "
import shutil, os
src = '/app/backend/data/app.db'
dst = f'/app/backend/data/backups/app-{__import__(\"datetime\").datetime.now().strftime(\"%Y%m%d_%H%M%S\")}.db'
shutil.copy2(src, dst)
print(f'Backup created: {dst}')
"
```

### Docker Environment Variables

To customize ports or other settings, create a `docker-compose.override.yml`:

```yaml
version: "3.8"
services:
  localrouter:
    environment:
      - BACKEND_PORT=8080
    ports:
      - "8080:8080"
```

---

## Linux Deployment (Production)

### Systemd Service

Create `/etc/systemd/system/localrouter.service`:

```ini
[Unit]
Description=LocalRouter - LLM API Routing Manager
After=network.target

[Service]
Type=simple
User=localrouter
Group=localrouter
WorkingDirectory=/opt/localrouter/backend
ExecStart=/opt/localrouter/backend/venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 12002
Restart=always
RestartSec=5
Environment=HOST=127.0.0.1
Environment=BACKEND_PORT=12002
StandardOutput=append:/var/log/localrouter/backend.log
StandardError=append:/var/log/localrouter/backend.log

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable localrouter
sudo systemctl start localrouter
sudo systemctl status localrouter
```

### Nginx Reverse Proxy

For public access with domain name:

```nginx
server {
    listen 80;
    server_name api.yourdomain.com;

    # Frontend
    location / {
        proxy_pass http://127.0.0.1:12001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Backend API
    location /api/ {
        proxy_pass http://127.0.0.1:12002;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Chat completions (streaming support)
    location /v1/ {
        proxy_pass http://127.0.0.1:12002;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 300s;
        proxy_buffering off;
    }
}
```

### Supervisor Configuration

```ini
[program:localrouter-backend]
command=/opt/localrouter/backend/venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 12002
directory=/opt/localrouter/backend
user=localrouter
autostart=true
autorestart=true
stderr_logfile=/var/log/localrouter/backend.err.log
stdout_logfile=/var/log/localrouter/backend.out.log
environment=HOST="127.0.0.1",BACKEND_PORT="12002"
```

---

## Windows Deployment

### Using Management Script

```cmd
scripts\manage.bat start
```

### Manual Installation

```cmd
:: Clone and setup
git clone https://github.com/licorxj/QM-LocalRouter.git
cd ApiRouteManeger

:: Initialize
cd scripts
python init_db.py
cd ..

:: Start backend (Terminal 1)
cd backend
venv\Scripts\activate
uvicorn app.main:app --host 0.0.0.0 --port 12002

:: Start frontend (Terminal 2)
cd frontend
npm install
npm run dev
```

### IIS Reverse Proxy (Optional)

For Windows Server with IIS:

1. Install URL Rewrite and Application Request Routing (ARR)
2. Add reverse proxy rules:
   - `/api/*` 鈫?`http://localhost:12002/api/*`
   - `/v1/*` 鈫?`http://localhost:12002/v1/*`
   - `/` 鈫?`http://localhost:12001/`

---

## macOS Deployment

```bash
# Clone and setup
git clone https://github.com/licorxj/QM-LocalRouter.git
cd ApiRouteManeger

# Initialize
cd scripts
chmod +x init_db.sh manage.sh
./init_db.sh

# Start services
./manage.sh start
```

For launchd auto-start, create `~/Library/LaunchAgents/com.localrouter.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.localrouter.backend</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>-m</string>
        <string>uvicorn</string>
        <string>app.main:app</string>
        <string>--host</string>
        <string>127.0.0.1</string>
        <string>--port</string>
        <string>12002</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/opt/localrouter/backend</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
```

---

## VPS Production Deployment

### Step 1: Create User

```bash
sudo useradd -r -s /bin/bash -m localrouter
sudo mkdir -p /opt/localrouter
sudo chown localrouter:localrouter /opt/localrouter
```

### Step 2: Clone & Setup

```bash
sudo -u localrouter git clone https://github.com/licorxj/QM-LocalRouter.git /opt/localrouter
cd /opt/localrouter

# Initialize
cd scripts
sudo -u localrouter python init_db.py
cd ..
```

### Step 3: Build Frontend

```bash
cd frontend
sudo -u localrouter npm install
sudo -u localrouter npm run build
```

### Step 4: Setup Systemd

```bash
# Create the service file as shown in the Linux section above
sudo cp docs/localrouter.service /etc/systemd/system/
sudo systemctl enable localrouter
sudo systemctl start localrouter
```

### Step 5: Configure Nginx

Install and configure nginx with the config shown in the Linux section. Enable HTTPS with Let's Encrypt:

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d api.yourdomain.com
```

---

## Kubernetes Deployment

Create a `k8s.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: localrouter
  labels:
    app: localrouter
spec:
  replicas: 1
  selector:
    matchLabels:
      app: localrouter
  template:
    metadata:
      labels:
        app: localrouter
    spec:
      containers:
      - name: localrouter
        image: localrouter:latest
        ports:
        - containerPort: 12002
          name: backend
        - containerPort: 12001
          name: frontend
        env:
        - name: BACKEND_PORT
          value: "12002"
        - name: FRONTEND_PORT
          value: "12001"
        volumeMounts:
        - name: data
          mountPath: /app/backend/data
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "1Gi"
            cpu: "500m"
      volumes:
      - name: data
        persistentVolumeClaim:
          claimName: localrouter-data
---
apiVersion: v1
kind: Service
metadata:
  name: localrouter
spec:
  selector:
    app: localrouter
  ports:
  - port: 12002
    targetPort: 12002
    name: backend
  - port: 12001
    targetPort: 12001
    name: frontend
  type: LoadBalancer
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: localrouter-data
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
```

---

## Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKEND_PORT` | `12002` | Backend uvicorn server port |
| `FRONTEND_PORT` | `12001` | Frontend Vite dev server port |
| `HOST` | `127.0.0.1` | Backend bind address (use `0.0.0.0` for Docker/VPS) |
| `DATABASE_URL` | `sqlite+aiosqlite:///data/app.db` | SQLite database path |
| `LOG_RETENTION_DAYS` | `30` | Days to keep request logs |
| `DEFAULT_TIMEOUT` | `120` | Default upstream request timeout (seconds) |
| `DEFAULT_RETRY_COUNT` | `2` | Default retry count for failed requests |

---

## Troubleshooting

### Backend won't start

```bash
# Check if port is already in use
lsof -i :12002
# Kill the process using the port
kill -9 <PID>
```

### Frontend shows blank page

```bash
# Check if backend is accessible from the frontend
curl http://localhost:12002/health
```

### Database issues

```bash
# Backup first
cp backend/data/app.db backend/data/app.db.bak

# Reset database (WARNING: Deletes all data)
rm backend/data/app.db
# Then restart the backend 鈥?it will recreate the database
```
