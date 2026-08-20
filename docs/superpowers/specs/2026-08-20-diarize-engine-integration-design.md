# diarize 库接入 ASR 工厂说话人识别引擎设计

日期：2026-08-20
状态：已确认

## 背景与目标

`diarize`（v0.1.2，已安装于 venv312）是纯本地 CPU 说话人识别库：
Silero VAD → WeSpeaker ResNet34-LM(ONNX) 说话人嵌入 → GMM BIC 自动估计说话人数 →
谱聚类，无需 API Key / HF Token，自动检测说话人数。

目标：将其作为第三种说话人识别引擎（引擎名 `diarize`）接入项目 ASR 后处理工厂，
并按用户决策**设为新的默认说话人引擎**（原默认 pyannote 依赖 HuggingFace 模型与 Token，
离线环境易失败）。

## 库 API（已核实源码）

```python
from diarize import diarize
result = diarize(audio_path, *, min_speakers=1, max_speakers=20, num_speakers=None)
result.segments      # [Segment(start, end, speaker), ...]（pydantic frozen 模型）
result.speakers      # 排序去重后的说话人标签列表
result.num_speakers  # 说话人数
```

**音频兼容性约束**：库内部用 `soundfile` 读音频（embeddings 阶段 `sf.read`），
无法读取 mp4/mkv 等视频容器。项目上游音源可能是视频文件，
故新处理器需在调用前用 ffmpeg 将非 soundfile 可读格式预转为 16kHz 单声道临时 WAV。

## 架构与改动点

沿用现有处理器模式（方案 A，已确认）：

### 1. 新处理器（backend/asr/speaker_diarization_processor.py）

新增 `DiarizeLibProcessor(SpeakerDiarizationProcessor)`：

- `diarize(audio_path, num_speakers=None, min_speakers=None, max_speakers=None, **kwargs)`
  - `**kwargs` 静默忽略 `model_name` / `hf_token` 等上游可能塞入的无关选项
  - 方法内懒加载 `from diarize import diarize as _lib_diarize`（与 whisperx/funasr 模式一致），
    缺失时抛清晰的 ImportError
  - 音频预转：先用 `soundfile.info` 探测，失败则经 `shutil.which("ffmpeg")` 转 16kHz 单声道
    临时 WAV，结束后清理
  - 结果映射：`Segment(start, end, speaker)` → 项目内 `SpeakerSegment`；
    `result.speakers` → 说话人列表，返回 `SpeakerDiarizationResult`

### 2. 引擎注册（backend/asr/asr_base.py `_apply_diarization`）

新增分支 `elif diarize_engine == "diarize"` → `DiarizeLibProcessor(**options)`，
复用现有 `merge_diarization_with_asr`（按时间重叠 ≥50% 将说话人标签分配给 ASR segments）。
docstring 示例引擎列表补充 `"diarize"`。

### 3. 默认引擎切换（用户已确认改变存量工作流默认行为）

- `backend/asr/asr_factory.py`：`_STAGE_DEFAULT_ENGINES["diarization"]`: `pyannote` → `diarize`
- `backend/steps/s_asr_stages.py`：同上
- `backend/config/config.yaml.temp`：`asr.post_process.diarization.engine`: `pyannote` → `diarize`

### 4. 节点配置 UI（backend/config/builtin_node_types.py `asr_postprocess` 节点）

`diarize_engine` 下拉新增：`{"value": "diarize", "label": "Diarize (纯本地/无需Key)"}`。
num_speakers / min_speakers / max_speakers 配置项已有，直接复用（s_asr_stages 会注入 diarize_options）。

### 5. 迁移规则核查（已核实，无需改动）

`backend/workflow_validation.py` 的 `NODE_CONFIG_MIGRATIONS` 无清理 `diarize_engine` 的规则。

## 容错

- 流水线各阶段本就独立 try/except（asr_base.post_process 与 run_post_process_pipeline），
  diarize 失败仅记录日志、不阻塞其他阶段
- 库调用失败（如无声语音频返回空 segments）按现有空结果路径处理

## 测试计划

1. 单元级：构造含两人以上语音的音频（或复用现有工作产物），调用
   `run_post_process_pipeline(asr_result, audio, stages=["diarization"], diarize_engine="diarize")`，
   验证 segments 带 `speaker` 字段、`speakers` 列表非空
2. 视频容器兼容：以 mp4 音源调用，验证 ffmpeg 预转路径生效
3. 回归：`pyannote` / `cam++` 仍可显式选用（dispatch 分支不被破坏）

## 明确不做（YAGNI）

- 不改 ASR 接口能力声明（asr_interfaces.json 的 speaker_diarization 能力位描述的是 ASR 引擎自身）
- 不引入 RTTM 导出能力到工作流产物
- 不改动 s02_asr 全流程节点的参数键
