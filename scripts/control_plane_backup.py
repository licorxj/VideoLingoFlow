import argparse
from pathlib import Path

from backend.control_plane.backup import create_backup, restore_backup


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup = subparsers.add_parser("backup")
    backup.add_argument("--database", type=Path, required=True)
    backup.add_argument("--workspace", type=Path, required=True)
    backup.add_argument("--output", type=Path, required=True)
    backup.add_argument("--redis-rdb", type=Path)
    restore = subparsers.add_parser("restore")
    restore.add_argument("--archive", type=Path, required=True)
    restore.add_argument("--database", type=Path, required=True)
    restore.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "backup":
        print(create_backup(args.database, args.workspace, args.output, args.redis_rdb))
    else:
        print(restore_backup(args.archive, args.database, args.workspace)["created_at"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
