# -*- coding: utf-8 -*-
"""创作流水线：阶段函数 + 异步执行器（对齐源系统"HTTP 触发 → 落库状态 → 前端轮询"语义）。

模块划分：
    novel.py       导入章节 / 事件提取（eventExtraction 模板）
    script.py      剧本（手动导入或事件→草稿） / 资产提取（scriptAssetExtraction 模板）
    assets.py      资产提示词润色 / 资产出图与重生（画风 prefix 注入）
    storyboard.py  分镜表 / 分镜面板(图提示词) / 分镜图与重生
    videos.py      视频提示词(videoPromptGeneration 模板) / 视频生成与重生 / 选定
    dubbing.py     角色-音色绑定（audioBindPrompt 模板 + 配音谷音色库）

执行模型：submit() 丢线程池后台跑，状态落各表字段（eventState/extractState/state），HTTP 轮询读取。
"""
from concurrent.futures import ThreadPoolExecutor

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tf-pipeline")


def session_scope_ctx():
    """阶段函数内部的 session 上下文（便于各模块统一导入）。"""
    from backend.control_plane.database import session_scope

    return session_scope()


def submit(fn, *args, **kwargs):
    """后台执行一个阶段函数（fire-and-forget，异常打印不抛出）。"""
    def _wrap():
        try:
            fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            import traceback

            print(f"[toonflow:pipeline] {fn.__module__}.{fn.__name__} failed: {exc}")
            traceback.print_exc()

    return _executor.submit(_wrap)
