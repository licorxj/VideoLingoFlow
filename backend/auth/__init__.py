"""认证与订阅模块包。

优先加载已编译的受保护二进制模块（backend/auth_binaries/cp312/<target>/backend/auth）；
缺少匹配产物时回退公开源码，保证开发环境可直接运行。
"""
from backend.binary_path import prepend_binary_path

prepend_binary_path("auth", __path__)
