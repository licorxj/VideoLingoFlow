import argparse
import json
from pathlib import Path

from backend.control_plane.database import session_scope
from backend.control_plane.legacy_import import import_history, scan_history, scan_voiceforge_sqlite


def main() -> None:
    parser = argparse.ArgumentParser(description="只读扫描并导入历史任务控制平面记录")
    parser.add_argument("--tasks-root", default="tasks")
    parser.add_argument("--workflows-root", default="backend/config/workflows")
    parser.add_argument("--voiceforge-db", default="voiceforge_data/voiceforge.db")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report")
    args = parser.parse_args()
    records = scan_history(Path(args.tasks_root), Path(args.workflows_root))
    with session_scope() as session:
        report = import_history(session, records, dry_run=args.dry_run)
    report["voiceforge"] = scan_voiceforge_sqlite(Path(args.voiceforge_db))
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        Path(args.report).write_text(encoded, encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
