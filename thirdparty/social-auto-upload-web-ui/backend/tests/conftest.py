"""共享 pytest fixtures + Flask before_request 清理。

Flask 在装饰器注册时捕获函数引用，monkeypatch `app._ensure_db` 无效。
我们在 autouse fixture 里仅移除 `_ensure_db`（按函数名识别），让 monkeypatch
真的能拦截。其他 before_request 钩子（如 `_before_publish`）保留。
"""
import pytest


@pytest.fixture(autouse=True)
def _drop_ensure_db_before_request_hook():
    """所有测试默认不走 `_ensure_db`（它会试图 init_database 覆盖测试 schema）。
    其他 before_request 钩子（如 `_before_publish`）保留原状。"""
    from app import app as flask_app
    saved_hooks = list(flask_app.before_request_funcs.get(None, []))
    flask_app.before_request_funcs[None] = [
        fn for fn in saved_hooks
        if getattr(fn, '__name__', None) != '_ensure_db'
    ]
    yield
    flask_app.before_request_funcs[None] = saved_hooks