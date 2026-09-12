# -*- coding: utf-8 -*-
"""Toonflow 创作流程迁移包。

制作流程 / Agent / Skill / 提示词资产基于 Toonflow (Apache-2.0) 迁移：
https://github.com/HBAI-Ltd/Toonflow-app —— 保留其 LICENSE 与 NOTICES（见本目录）。

模块布局：
    core/     数据模型(tf_ 表)、种子、工作区(FlowData)、路径约定
    engines/  AI 能力适配层（本项目 LLM/生图/生视频/TTS/音乐 工厂 → Toonflow 契约）
    agents/   决策→子Agent→监督 三层编排 + skill 加载 + 自建 tool-loop
    api/      FastAPI 路由（/api/tf/*）
    skills/   data/skills 原样资产（18 主技能 + 画风/题材/技法库，文案零改动）
"""
