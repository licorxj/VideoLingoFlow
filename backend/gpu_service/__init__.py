"""GPU Service Layer: 常驻 GPU 任务服务。

与 TTS 服务层（OmniVoice/VoxCPM 等独立本地服务）同思路：
- manager 主进程：监测显存、按剩余显存动态分配 lane（进程）、任务排队调度、空闲超时释放
- lane 工作子进程：加载模型后常驻复用，空闲固定时长后退出释放显存
- client：worker 侧步骤提交任务到 Redis 队列并等待结果，服务不可用时回退进程内执行
"""
