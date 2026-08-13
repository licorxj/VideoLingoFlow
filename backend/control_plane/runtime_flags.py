"""运行时开关（内存态）。

启动时由 backend/main.py 依据环境变量初始化，控制面接口（POST /api/control/remote-mode）
写入配置的同时实时更新此处标志，使开关立即生效、无需重启。
"""

remote_mode_enabled: bool = False
