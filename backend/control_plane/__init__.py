"""控制面执行包。

优先加载已编译的受保护运行中枢（backend/control_plane_binaries/cp312/<target>/backend/control_plane）；
缺少匹配产物时回退公开源码，保证开发环境可直接运行。
"""
from backend.binary_path import prepend_binary_path

prepend_binary_path("control_plane", __path__)

from backend.control_plane.database import check_schema, configure_database, session_scope
from backend.control_plane.models import Base

__all__ = ["Base", "check_schema", "configure_database", "session_scope"]
