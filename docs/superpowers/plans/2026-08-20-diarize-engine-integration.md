# diarize 引擎接入 ASR 工厂实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将已安装的 `diarize` 库（引擎名 `diarize`）作为第三种说话人识别引擎接入 ASR 后处理工厂，并设为默认引擎。

**Architecture:** 沿用现有处理器模式——在 `speaker_diarization_processor.py` 新增 `DiarizeLibProcessor`，在 `asr_base.py::_apply_diarization` 注册引擎名，复用 `merge_diarization_with_asr` 合并说话人标签；同步切换 `_STAGE_DEFAULT_ENGINES` 与配置模板默认值，节点 UI 增加选项。

**Tech Stack:** Python 3.12（venv312），diarize 0.1.2（Silero VAD + WeSpeaker ONNX + 谱聚类），ffmpeg 预转兼容视频容器。

**项目约定：** 无 pytest/无 tests 目录，验证用临时独立脚本（venv312 python.exe 执行后清理）；本次任务不做 git 提交（用户未要求）。

**规格文档：** `docs/superpowers/specs/2026-08-20-diarize-engine-integration-design.md`

---

### Task 1: 新增 DiarizeLibProcessor

**Files:**
- Modify: `backend/asr/speaker_diarization_processor.py`（在 `CamPlusDiarizationProcessor` 类之后、`assign_speakers_to_segments` 之前插入新类）
- Verify: 临时脚本 `temp/verify_diarize_processor.py`（用完删除）

- [ ] **Step 1: 编写验证脚本（结果映射 + 无效参数）**

写入 `temp/verify_diarize_processor.py`：

```python
import sys
sys.path.insert(0, r"y:\VideoLingoLc")
from backend.asr.speaker_diarization_processor import DiarizeLibProcessor

proc = DiarizeLibProcessor()
# 1) 无关选项静默忽略（构造器接受 model_name/hf_token 不报错）
proc2 = DiarizeLibProcessor(model_name="x", hf_token="y")

# 2) 结果映射：用库的真实 Segment 类型
from diarize.utils import Segment
fake = type("R", (), {
    "segments": [Segment(start=0.5, end=4.2, speaker="SPEAKER_00"),
                 Segment(start=5.0, end=9.1, speaker="SPEAKER_01")],
})()
fake.speakers = ["SPEAKER_00", "SPEAKER_01"]
res = proc._parse_result(fake)
assert [s.speaker for s in res.segments] == ["SPEAKER_00", "SPEAKER_01"]
assert res.segments[0].start == 0.5 and res.segments[1].end == 9.1
assert res.speakers == ["SPEAKER_00", "SPEAKER_01"]
print("OK: DiarizeLibProcessor mapping verified")
```

- [ ] **Step 2: 运行确认失败**

Run: `y:\VideoLingoLc\venv312\python.exe temp/verify_diarize_processor.py`
Expected: FAIL，`ImportError: cannot import name 'DiarizeLibProcessor'`

- [ ] **Step 3: 实现 DiarizeLibProcessor**

在 `speaker_diarization_processor.py` 的 `CamPlusDiarizationProcessor` 类定义结束后追加：

```python
class DiarizeLibProcessor(SpeakerDiarizationProcessor):
    """diarize 库说话人识别处理器（纯本地 CPU）

    基于已安装的 `diarize` 包（Silero VAD + WeSpeaker ResNet34-LM 嵌入 +
    GMM BIC 自动估计说话人数 + 谱聚类），无需 API Key / HF Token。
    """

    def diarize(self, audio_path: str,
                num_speakers: Optional[int] = None,
                min_speakers: Optional[int] = None,
                max_speakers: Optional[int] = None,
                **kwargs) -> SpeakerDiarizationResult:
        """使用 diarize 库进行说话人识别。

        kwargs 静默忽略 model_name / hf_token 等上游可能注入的无关选项。
        """
        try:
            from diarize import diarize as _lib_diarize
        except ImportError:
            raise ImportError("diarize package required for 'diarize' diarization engine")

        converted = self._ensure_readable_audio(audio_path)
        try:
            call_kwargs: Dict[str, Any] = {}
            if num_speakers:
                call_kwargs["num_speakers"] = int(num_speakers)
            if min_speakers:
                call_kwargs["min_speakers"] = int(min_speakers)
            if max_speakers:
                call_kwargs["max_speakers"] = int(max_speakers)

            print(f"[Diarization] Running local diarize library: {os.path.basename(audio_path)}")
            result = _lib_diarize(converted, **call_kwargs)
        finally:
            if converted != audio_path:
                try:
                    os.unlink(converted)
                except OSError:
                    pass

        parsed = self._parse_result(result)
        print(f"[Diarization] diarize library completed: "
              f"{len(parsed.speakers)} speaker(s), {len(parsed.segments)} segment(s)")
        return parsed

    def _parse_result(self, result: Any) -> SpeakerDiarizationResult:
        """将 diarize 库的 DiarizeResult 映射为项目内数据结构。"""
        segments = [
            SpeakerSegment(start=float(seg.start), end=float(seg.end), speaker=seg.speaker)
            for seg in result.segments
        ]
        return SpeakerDiarizationResult(segments=segments, speakers=list(result.speakers))

    def _ensure_readable_audio(self, audio_path: str) -> str:
        """soundfile 无法读取的格式（mp4/mkv 等视频容器）经 ffmpeg 预转为 16kHz 单声道 WAV。

        可读时原样返回路径；转换后返回临时 WAV 路径（调用方负责清理）。
        """
        try:
            import soundfile as sf
            sf.info(audio_path)
            return audio_path
        except Exception:
            pass

        import shutil
        import subprocess
        import tempfile
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError(
                f"Audio format not readable by soundfile and ffmpeg not found: {audio_path}")

        tmp_path = os.path.join(tempfile.mkdtemp(prefix="diarize_lib_"), "audio.wav")
        cmd = [ffmpeg, "-y", "-i", audio_path, "-vn", "-ac", "1", "-ar", "16000", tmp_path]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg conversion failed: {proc.stderr[-500:]}")
        print(f"[Diarization] Converted to temp WAV for diarize library: {tmp_path}")
        return tmp_path
```

文件顶部 `from typing import List, Dict, Tuple, Optional, Any` 已含所需类型，无需修改导入。

- [ ] **Step 4: 运行验证脚本确认通过**

Run: `y:\VideoLingoLc\venv312\python.exe temp/verify_diarize_processor.py`
Expected: 输出 `OK: DiarizeLibProcessor mapping verified`

---

### Task 2: asr_base.py 引擎注册

**Files:**
- Modify: `backend/asr/asr_base.py`（`_apply_diarization` 约 L232-258）

- [ ] **Step 1: 新增 dispatch 分支与导入**

将 `_apply_diarization` 中的：

```python
        from backend.asr.speaker_diarization_processor import (
            PyannoteDiarizationProcessor,
            CamPlusDiarizationProcessor,
            merge_diarization_with_asr
        )
        
        # Select diarization processor
        if diarize_engine == "pyannote":
            processor = PyannoteDiarizationProcessor(**options)
        elif diarize_engine == "cam++":
            processor = CamPlusDiarizationProcessor(**options)
        else:
            raise ValueError(f"Unknown diarization engine: {diarize_engine}")
```

改为：

```python
        from backend.asr.speaker_diarization_processor import (
            PyannoteDiarizationProcessor,
            CamPlusDiarizationProcessor,
            DiarizeLibProcessor,
            merge_diarization_with_asr
        )
        
        # Select diarization processor
        if diarize_engine == "pyannote":
            processor = PyannoteDiarizationProcessor(**options)
        elif diarize_engine == "cam++":
            processor = CamPlusDiarizationProcessor(**options)
        elif diarize_engine == "diarize":
            processor = DiarizeLibProcessor(**options)
        else:
            raise ValueError(f"Unknown diarization engine: {diarize_engine}")
```

- [ ] **Step 2: 更新两处 docstring 的引擎示例**

`post_process` 与 `_apply_diarization` 的 docstring 中：
`Diarization engine name (e.g., "pyannote", "cam++").` →
`Diarization engine name (e.g., "pyannote", "cam++", "diarize").`

- [ ] **Step 3: 语法检查**

Run: `y:\VideoLingoLc\venv312\python.exe -c "import ast; ast.parse(open(r'y:\VideoLingoLc\backend\asr\asr_base.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

---

### Task 3: 切换默认引擎

**Files:**
- Modify: `backend/asr/asr_factory.py`（L208 `_STAGE_DEFAULT_ENGINES`）
- Modify: `backend/steps/s_asr_stages.py`（L29 `_STAGE_DEFAULT_ENGINES`）
- Modify: `backend/config/config.yaml.temp`（L73-74）

- [ ] **Step 1: asr_factory.py**

```python
_STAGE_DEFAULT_ENGINES = {"vad": "fsmn", "alignment": "whisperx", "diarization": "pyannote"}
```
→
```python
_STAGE_DEFAULT_ENGINES = {"vad": "fsmn", "alignment": "whisperx", "diarization": "diarize"}
```

- [ ] **Step 2: s_asr_stages.py**（同样一行）

- [ ] **Step 3: config.yaml.temp**

```yaml
    diarization:
      engine: pyannote
```
→
```yaml
    diarization:
      engine: diarize
```

- [ ] **Step 4: 语法检查两文件（同 Task 2 Step 3 的方式）**

---

### Task 4: 节点 UI 选项

**Files:**
- Modify: `backend/config/builtin_node_types.py`（`asr_postprocess` 节点 `diarize_engine` select，约 L383-387）

- [ ] **Step 1: 下拉新增选项**

```python
                {"value": "pyannote", "label": "Pyannote"},
                {"value": "cam++", "label": "CAM++ (FunASR)"},
```
→
```python
                {"value": "diarize", "label": "Diarize (纯本地/无需Key)"},
                {"value": "pyannote", "label": "Pyannote"},
                {"value": "cam++", "label": "CAM++ (FunASR)"},
```

- [ ] **Step 2: 语法检查（同 Task 2 Step 3）**

---

### Task 5: 端到端验证与清理

- [ ] **Step 1: 真实音频验证**

在 `data/workspace` 或 `output` 下寻找现成 wav 音频（优先多人声）；若无，用 venv ffmpeg 生成 10s 测试 wav。写临时脚本走完整 dispatch：

```python
import sys
sys.path.insert(0, r"y:\VideoLingoLc")
from backend.asr.asr_factory import run_post_process_pipeline

asr_result = {"language": "zh", "segments": [
    {"id": 1, "start": 0.0, "end": 8.0, "text": "测试文本"},
]}
out = run_post_process_pipeline(asr_result, r"<音频路径>",
                                stages=["diarization"], diarize_engine="diarize")
print("speakers:", out.get("speakers"))
print("seg speakers:", [s.get("speaker") for s in out["segments"]])
assert out.get("speakers"), "no speakers assigned"
print("OK")
```

Run: `y:\VideoLingoLc\venv312\python.exe temp/verify_e2e.py`
Expected: 输出 speakers 列表与 `OK`（单人声音频允许 speakers 长度为 1）

- [ ] **Step 2: 回归验证** —— 确认未知引擎仍抛 ValueError、pyannote 分支未破坏：

```python
from backend.asr.asr_base import ASRBase
class T(ASRBase):
    def transcribe(self, *a, **k): return {}
try:
    T()._apply_diarization({}, "x.wav", "not_exist", {})
    raise AssertionError("should raise")
except ValueError as e:
    print("OK:", e)
```

- [ ] **Step 3: 清理** —— 删除 `temp/verify_diarize_processor.py`、`temp/verify_e2e.py` 及临时音频

- [ ] **Step 4: GetProblems 检查四个修改文件无编译/lint 错误**
