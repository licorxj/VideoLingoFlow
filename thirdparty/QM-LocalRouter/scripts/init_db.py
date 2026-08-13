#!/usr/bin/env python3
"""
LocalRouter - Database Initialization Script
Initializes the SQLite database and creates the initial schema.

Usage:
    python init_db.py

This script will:
  1. Create Python virtual environment (if not exists)
  2. Install backend dependencies
  3. Create .env file (if not exists)
  4. Create data directories
  5. Initialize the SQLite database
"""

import os
import sys
import subprocess
import asyncio
from pathlib import Path

# Project root is the parent of scripts/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
DATA_DIR = BACKEND_DIR / "data"
ENV_FILE = BACKEND_DIR / ".env"
REQUIREMENTS = BACKEND_DIR / "requirements.txt"
VENV_DIR = BACKEND_DIR / "venv"


def print_step(msg: str):
    print(f"  >> {msg}")


def run_cmd(cmd: list, cwd: str = None) -> bool:
    try:
        subprocess.run(cmd, cwd=cwd or str(PROJECT_ROOT), check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except subprocess.CalledProcessError as e:
        print(f"  ERROR: {e.stderr.decode() if e.stderr else str(e)}")
        return False


def setup_venv() -> bool:
    """Create virtual environment if not exists."""
    venv_python = VENV_DIR / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if venv_python.exists():
        print_step("Virtual environment already exists, skipping creation.")
        return True

    print_step("Creating Python virtual environment...")
    return run_cmd([sys.executable, "-m", "venv", str(VENV_DIR)])


def get_pip() -> str:
    """Get pip executable path from venv."""
    if sys.platform == "win32":
        return str(VENV_DIR / "Scripts" / "pip.exe")
    return str(VENV_DIR / "bin" / "pip")


def install_deps() -> bool:
    """Install requirements from requirements.txt."""
    if not REQUIREMENTS.exists():
        print_step(f"Requirements file not found: {REQUIREMENTS}")
        return False

    print_step("Installing backend dependencies...")
    pip = get_pip()
    return run_cmd([pip, "install", "-r", str(REQUIREMENTS)])


def setup_env() -> bool:
    """Create default .env file if not exists."""
    if ENV_FILE.exists():
        print_step(".env file already exists, skipping.")
        return True

    print_step("Creating default .env file...")
    try:
        ENV_FILE.write_text(
            "APP_NAME=LLM API Router\n"
            "APP_VERSION=1.0.0\n"
            f"HOST=127.0.0.1\n"
            f"BACKEND_PORT=12002\n"
            f"DATABASE_URL=sqlite+aiosqlite:///{DATA_DIR}/app.db\n"
            f"LOG_RETENTION_DAYS=30\n"
            f"DEFAULT_TIMEOUT=120\n"
            f"DEFAULT_RETRY_COUNT=2\n",
            encoding="utf-8"
        )
        return True
    except IOError as e:
        print_step(f"Failed to create .env: {e}")
        return False


def setup_directories() -> bool:
    """Create required data directories."""
    dirs = [DATA_DIR, DATA_DIR / "backups", DATA_DIR / "icons"]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    print_step("Data directories created.")
    return True


async def init_database() -> bool:
    """Initialize the SQLite database using the app's init_db()."""
    print_step("Initializing database...")

    # Add backend directory to sys.path so we can import app modules
    sys.path.insert(0, str(BACKEND_DIR))

    try:
        # Need to set up the environment before importing
        os.environ.setdefault("BACKEND_PORT", "12002")
        os.environ.setdefault("HOST", "127.0.0.1")

        from app.database import init_db, engine

        await init_db()
        await engine.dispose()

        db_file = DATA_DIR / "app.db"
        if db_file.exists():
            print_step(f"Database created successfully: {db_file}")
            return True
        else:
            print_step(f"Database file not found at {db_file}")
            return False
    except Exception as e:
        print_step(f"Database initialization failed: {e}")
        return False


def main():
    print("=" * 54)
    print("  LocalRouter - Database Initialization")
    print("=" * 54)

    # Step 1: Setup directories
    print("\n[1/5] Creating data directories...")
    if not setup_directories():
        sys.exit(1)

    # Step 2: Create virtual environment
    print("\n[2/5] Setting up Python virtual environment...")
    if not setup_venv():
        sys.exit(1)

    # Step 3: Install dependencies
    print("\n[3/5] Installing Python dependencies...")
    if not install_deps():
        sys.exit(1)

    # Step 4: Create .env file
    print("\n[4/5] Setting up environment configuration...")
    if not setup_env():
        sys.exit(1)

    # Step 5: Initialize database
    print("\n[5/5] Initializing database...")
    asyncio.run(init_database())

    print("\n" + "=" * 54)
    print("  Initialization complete!")
    print(f"  Database: {DATA_DIR / 'app.db'}")
    print(f"  Backend:  http://localhost:12002")
    print(f"  Docs:     http://localhost:12002/docs")
    print("=" * 54)
    print("\nNext steps:")
    print("  1. Start the backend:")
    print("     Windows: backend\\venv\\Scripts\\python -m uvicorn app.main:app --host 0.0.0.0 --port 12002")
    print("     Linux:   backend/venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 12002")
    print("  2. Start the frontend (in a separate terminal):")
    print("     cd frontend && npm install && npm run dev")
    print("  3. Open http://localhost:12001 in your browser")
    print()


if __name__ == "__main__":
    main()
