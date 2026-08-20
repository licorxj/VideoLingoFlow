# 标点恢复后处理阶段（CT-Punc）设计

日期：2026-08-20
状态：已确认（用户批准方案 A + 智能兜底 + 只插标点 + 仅中英 + 语言兼容归一化）

## 背景与目标

部分 ASR 引擎输出文本缺少标点。将 FunASR 的 CT-Punc 标点恢复模型做成
ASR 后处理流水线的**第四个阶段**（与 VAD / 对齐 / 说话人识别同级），
固定位于所有阶段最后，作为无标点能力引擎的智能候补。
前端调用入口放在 asr_postprocess 节点之上。

## 已确认决策

| 决策点 | 结论 |
|---|---|
| 触发策略 | 智能兜底：阶段默认启用，运行时检测标点密度，足够则跳过 |
| 处理深度 | 只回写 `segment["text"]`，不拆分 segment，不动 words/时间戳/speaker |
| 语言范围 | 仅 zh/en 执行，其余语言跳过并记日志 |
| 语言兼容 | 归一化函数兼容 `zh`/`Chinese`/`China`/`zh-CN`、`en`/`English`/`EN` 等变体 |
| 阶段位置 | `("vad", "alignment", "diarization", "punctuation")` 最后 |

## 架构

### 阶段接线（与现有三阶段对称）

- `asr_factory.py`：`_POST_PROCESS_STAGE_ORDER` 追加 `"punctuation"`；
  `_STAGE_DEFAULT_ENGINES["punctuation"] = "ct_punc"`；新增 `run_punctuation()`；
  `run_post_process_pipeline` 增加 `punctuation_engine` / `punctuation_options`。
- `asr_base.py`：新增 `_apply_punctuation` dispatch（`"ct_punc"` → 处理器）。
- 引擎解析优先级继承现有机制：节点配置 > 全局设置
  （`asr.post_process.punctuation.engine`）> 内置默认。

### 核心模块 `backend/asr/punctuation_processor.py`（新建）

1. `normalize_lang_code(lang)`：别名表 + BCP47 前缀匹配，
   zh 系 → `"zh"`，en 系 → `"en"`，`auto`/空 → `""`，其余原样小写。
2. `_needs_punctuation(segments, threshold=0.005)`：标点字符
   （`。！？，、；：,.!?;:`）占比 < 0.5% 判定需要恢复；总字符为 0 返回 False。
3. `PunctuationProcessor` 基类 + `CtPuncPunctuationProcessor`：
   - 语言门控（非 zh/en 跳过）+ 密度检测（足够则跳过）
   - 懒加载 FunASR `AutoModel(model=<本地缓存 or "ct-punc">)`，
     模块级 dict 单例缓存跨任务复用（模型 ~1GB）
   - 本地路径：`_model_cache/models/iic/punc_ct-transformer_cn-en-common-vocab471067-large`
     （与 `funasr_nano._local_submodel` 一致）
   - 逐 segment `generate(input=text)`，单段失败保留原文
   - 顶层 `text` 用恢复后的 segments 重新拼接（zh 无分隔、en 空格）

### 容错

阶段独立 try/except（流水线既有约定）：失败仅记日志、返回输入结果。
`funasr` 缺失时抛明确 ImportError。

## 前端节点 UI（asr_postprocess）

- `defaultConfig`：`run_punctuation: True`、`punc_engine: ""`
- `configFields`：复选框「执行标点恢复」+ 引擎下拉
  （跟随全局设置 / CT-Punc (FunASR)），`dependsOn` 联动
- 节点 description 更新为「VAD断句 / 时间戳对齐 / 说话人识别 / 标点恢复」
- 实施时复查 `workflow_validation.py` 迁移规则不清理新键

## 明确不做（YAGNI）

- 不按句末标点重新拆分 segment（与 VAD 职责重叠）
- 不做可配置语言白名单、不做标点风格选项
- 不做批量推理优化（逐段处理已够用）

## 测试计划

1. `normalize_lang_code` 全变体用例（auto/空/未知/BCP47）
2. 标点密度检测边界（空文本、临界值）
3. e2e：无标点 ASR JSON → `run_punctuation` → 标点补齐，words/时间戳不变
4. 回归：已带标点 → 跳过、输出不变
5. 语法检查（ast.parse）
