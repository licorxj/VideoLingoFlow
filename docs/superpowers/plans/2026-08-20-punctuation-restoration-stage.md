# 标点恢复后处理阶段实施计划

> 配套 spec：`docs/superpowers/specs/2026-08-20-punctuation-restoration-stage-design.md`

**Goal:** CT-Punc 标点恢复作为 ASR 后处理第四阶段，智能兜底、仅中英、只插标点。

### Task 1: 核心处理器
- Create: `backend/asr/punctuation_processor.py`
- `normalize_lang_code` / `_needs_punctuation` / `CtPuncPunctuationProcessor`（模块级模型缓存）
- 验证：语法检查 + 归一化/密度检测单元脚本

### Task 2: ASRBase dispatch
- Modify: `backend/asr/asr_base.py` — `_apply_punctuation`（引擎 `ct_punc`），
  `post_process` docstring 同步

### Task 3: 工厂接线
- Modify: `backend/asr/asr_factory.py` — `_POST_PROCESS_STAGE_ORDER`、
  `_STAGE_DEFAULT_ENGINES`、`run_punctuation()`、pipeline 参数与阶段执行

### Task 4: 步骤层接线
- Modify: `backend/steps/s_asr_stages.py` — engines/options 加 punctuation，
  pipeline 调用传参（引擎解析：节点 > 全局 > 默认）

### Task 5: 节点 UI 与全局配置
- Modify: `backend/config/builtin_node_types.py` — defaultConfig +
  configFields + description
- Modify: `backend/config/config.yaml.temp` — `asr.post_process.punctuation.engine`
- 复查 `workflow_validation.py` 迁移规则

### Task 6: 端到端验证
- 无标点 JSON → 标点补齐（words/时间戳不变）；已带标点 → 跳过；回归现有阶段不受影响
