"""Quick check: are there any running/queued tasks?"""
import sqlite3, os, json
from datetime import datetime

db_path = os.path.join(os.path.dirname(__file__), "..", "control-plane.db")
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

# Check all non-terminal tasks
rows = conn.execute(
    "SELECT id, status, created_at, updated_at, payload FROM cp_tasks "
    "WHERE status NOT IN ('succeeded', 'failed', 'cancelled', 'deleted', 'created') "
    "ORDER BY created_at DESC"
).fetchall()

if not rows:
    print("✅ 当前没有正在运行或排队的任务。")
else:
    print(f"⚠️  发现 {len(rows)} 个活跃任务：")
    print("-" * 80)
    for r in rows:
        payload = {}
        try:
            payload = json.loads(r["payload"]) if r["payload"] else {}
        except:
            pass
        name = payload.get("name", "") or payload.get("workflow", {}).get("name", "") or "（未命名）"
        print(f"  ID: {r['id']}")
        print(f"  状态: {r['status']}")
        print(f"  名称: {name}")
        print(f"  创建: {r['created_at']}")
        print(f"  更新: {r['updated_at']}")
        print()

# Also show summary of ALL statuses
print("\n📊 全部任务状态统计：")
stat_rows = conn.execute(
    "SELECT status, COUNT(*) as cnt FROM cp_tasks GROUP BY status ORDER BY cnt DESC"
).fetchall()
for r in stat_rows:
    print(f"  {r['status']}: {r['cnt']}")

conn.close()
