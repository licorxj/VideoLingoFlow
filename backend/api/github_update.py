# -*- coding: utf-8 -*-
"""GitHub 更新接口：拉取最新代码并调用项目根目录安装脚本。"""
from fastapi import APIRouter

from backend.updater import github_updater


router = APIRouter(prefix="/api/github-update")


@router.post("/run")
async def run_update():
    """启动 GitHub 更新任务（拉取代码 + 执行安装脚本），后台异步执行。"""
    return github_updater.run_update()


@router.get("/status")
async def update_status():
    """查询 GitHub 更新任务进度。"""
    return github_updater.get_status()
