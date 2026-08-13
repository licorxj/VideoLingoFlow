"""验证 /api/v2/drafts 透传 platformOverrides / accountOverrides / platformChecked / accountChecked。
实施前必跑——如果失败则需要改后端（参考 spec §4.4）。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests

BASE = "http://127.0.0.1:5409/api/v2"
NEW_KEYS = {
    "platformOverrides": {"douyin": {"title": "ov-title"}},
    "accountOverrides": {"1": {"title": "acc-ov-title"}},
    "platformChecked": {"douyin": True},
    "accountChecked": {"1": True},
}


def test_drafts_passthrough():
    draft_data = {
        "commonConfig": {},
        "platformConfigs": {},
        **NEW_KEYS,
    }
    payload = {
        "type": "video",
        "name": "verify-draft-passthrough",
        "draft_data": draft_data,
    }
    r = requests.post(f"{BASE}/drafts", json=payload, timeout=5)
    assert r.status_code == 200, f"POST 失败: {r.status_code} {r.text}"
    draft_id = r.json()["data"]["id"]

    r2 = requests.get(f"{BASE}/drafts/{draft_id}", timeout=5)
    assert r2.status_code == 200
    body = r2.json()["data"]
    data = body["draft_data"]
    if isinstance(data, str):
        data = json.loads(data)

    for key, expected in NEW_KEYS.items():
        assert data.get(key) == expected, f"键 {key} 透传失败: 期望 {expected}, 实际 {data.get(key)}"
    print("✓ 草稿后端透传 4 个新键成功")

    # 清理
    requests.delete(f"{BASE}/drafts/{draft_id}", timeout=5)


if __name__ == "__main__":
    test_drafts_passthrough()
