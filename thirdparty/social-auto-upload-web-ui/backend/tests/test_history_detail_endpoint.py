"""
测试 GET /api/v2/history/<batch_id> 单批次详情端点。
- 200：返回 batch + items（与列表 item 结构一致）
- 404：不存在的 batch_id
- 200 + items=[]：存在 batch 但无明细
- 账号已删除但 detail 仍保留 account_name 历史值
- duration 计算：started_at+finished_at 有 → 整数秒；缺 → null
"""
import os
import sys
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS publish_batches (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    video_material_id TEXT DEFAULT '',
    image_material_ids TEXT DEFAULT '[]',
    landscape_cover_material_id TEXT DEFAULT '',
    portrait_cover_material_id TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    account_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    schedule_time TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS publish_details (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    account_id INTEGER,
    account_name TEXT NOT NULL DEFAULT '',
    platform TEXT NOT NULL DEFAULT '',
    account_configs TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    error_message TEXT NOT NULL DEFAULT '',
    publish_url TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    FOREIGN KEY (batch_id) REFERENCES publish_batches(id) ON DELETE CASCADE
);
"""


class TestHistoryDetailEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp()
        os.environ['SAU_DATA_DIR'] = cls._tmpdir
        cls.DB_PATH = Path(cls._tmpdir) / "db" / "database.db"
        cls.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(cls.DB_PATH))
        conn.executescript(_SCHEMA_SQL)
        # b1: 3 账号全成功，b1 本身 started_at/finished_at 都有
        conn.execute(
            "INSERT INTO publish_batches (id, type, title, status, account_count, success_count, failed_count, created_at, started_at, finished_at) "
            "VALUES ('b1', 'video', '测试视频', 'success', 3, 3, 0, '2026-06-01 10:00:00', '2026-06-01 10:00:00', '2026-06-01 10:00:08')"
        )
        # b2: 2 账号 1 失败
        conn.execute(
            "INSERT INTO publish_batches (id, type, title, status, account_count, success_count, failed_count, created_at) "
            "VALUES ('b2', 'image', '测试图文', 'partial', 2, 1, 1, '2026-06-02 10:00:00')"
        )
        # b3: 存在但无明细
        conn.execute(
            "INSERT INTO publish_batches (id, type, title, status, account_count, success_count, failed_count, created_at) "
            "VALUES ('b3', 'video', '空批次', 'pending', 0, 0, 0, '2026-06-03 10:00:00')"
        )
        # b1 的 3 个明细，d1 给了 started/finished（duration=8s）
        conn.execute("INSERT INTO publish_details (id, batch_id, account_id, account_name, platform, account_configs, status, started_at, finished_at) VALUES ('d1', 'b1', 101, '账号A', '抖音', '{\"title\":\"测试视频\"}', 'success', '2026-06-01 10:00:00', '2026-06-01 10:00:08')")
        conn.execute("INSERT INTO publish_details (id, batch_id, account_id, account_name, platform, account_configs, status) VALUES ('d2', 'b1', 102, '账号B', '小红书', '{\"title\":\"测试视频\"}', 'success')")
        # d3: account_id=999（已删除账号）但 account_name 保留
        conn.execute("INSERT INTO publish_details (id, batch_id, account_id, account_name, platform, account_configs, status) VALUES ('d3', 'b1', 999, '账号C(已删)', 'B站', '{}', 'success')")
        # b2 的明细
        conn.execute("INSERT INTO publish_details (id, batch_id, account_id, account_name, platform, account_configs, status) VALUES ('d4', 'b2', 201, '账号D', '抖音', '{}', 'success')")
        conn.execute("INSERT INTO publish_details (id, batch_id, account_id, account_name, platform, account_configs, status, error_message) VALUES ('d5', 'b2', 202, '账号E', '小红书', '{}', 'failed', 'cookie 过期')")
        conn.commit()
        conn.close()
        from ext_api import app
        cls.client = app.test_client()

    def setUp(self):
        self._db_path_patch = patch('ext_api.DB_PATH', self.DB_PATH)
        self._db_path_patch.start()

    def tearDown(self):
        self._db_path_patch.stop()

    def test_returns_batch_with_items(self):
        """存在 batch + items：200，data 包含 batch 字段 + items 数组，account_configs 已反序列化"""
        resp = self.client.get('/api/v2/history/b1')
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body['code'], 200)
        data = body['data']
        self.assertEqual(data['id'], 'b1')
        self.assertEqual(data['title'], '测试视频')
        self.assertEqual(data['account_count'], 3)
        self.assertEqual(len(data['items']), 3)
        # d1 的 account_configs 已被反序列化为 dict
        d1 = next(d for d in data['items'] if d['id'] == 'd1')
        self.assertEqual(d1['account_configs'], {'title': '测试视频'})
        # d1 计算出 duration=8
        self.assertEqual(d1['duration'], 8)
        # d2 没有 started/finished，duration=None
        d2 = next(d for d in data['items'] if d['id'] == 'd2')
        self.assertIsNone(d2['duration'])

    def test_404_when_batch_not_found(self):
        """不存在的 batch：404，code=404，msg 含"不存在\""""
        resp = self.client.get('/api/v2/history/does-not-exist')
        self.assertEqual(resp.status_code, 404)
        body = resp.get_json()
        self.assertEqual(body['code'], 404)
        self.assertIn('不存在', body['msg'])

    def test_empty_items(self):
        """存在 batch 但无明细：200，items=[]"""
        resp = self.client.get('/api/v2/history/b3')
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body['code'], 200)
        self.assertEqual(body['data']['id'], 'b3')
        self.assertEqual(body['data']['items'], [])

    def test_deleted_account_keeps_account_name(self):
        """账号已删除（account_id 在 store 找不到）：200，item.account_name 仍保留历史值"""
        resp = self.client.get('/api/v2/history/b1')
        body = resp.get_json()
        d3 = next(d for d in body['data']['items'] if d['id'] == 'd3')
        self.assertEqual(d3['account_id'], 999)
        self.assertEqual(d3['account_name'], '账号C(已删)')

    def test_failed_item_includes_error_message(self):
        """失败 item 含 error_message 字段"""
        resp = self.client.get('/api/v2/history/b2')
        body = resp.get_json()
        d5 = next(d for d in body['data']['items'] if d['id'] == 'd5')
        self.assertEqual(d5['status'], 'failed')
        self.assertEqual(d5['error_message'], 'cookie 过期')
