# VideoLingo 节点目录（Node Catalog）

> 自动生成时间：2026-09-01 08:19:25  
> 节点总数：88　（带 `*` 的接口为必填项）

## 总览

| 分组 | 节点数 |
|------|-------|
| 输入输出节点（`io`） | 5 |
| 预览节点（`preview`） | 3 |
| 音频处理节点（`audio`） | 10 |
| 视频处理节点（`video`） | 14 |
| AI生成类节点（`ai_gen`） | 17 |
| 翻译相关节点（`translation`） | 14 |
| AIGC流程链（`aigc`） | 3 |
| 智能体（`agent`） | 2 |
| 流程控制节点（`flow_control`） | 2 |
| 网络请求类节点（`network_request`） | 4 |
| 工具类节点（`utility`） | 9 |
| 文件操作类节点（`file`） | 3 |
| 组合节点（`group_node`） | 2 |

## 节点详情

### 输入输出节点（`io`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| 产物文件归档 | `archive_artifacts` | 将上游多个产物文件归档到指定目录，支持复制/剪切、新建子文件夹、重命名与自动序号 | thread | 产物输入(`any`:any) | 归档路径(`output`:any) |
| 文件加载 | `file_load` | 在卡片上选择或输入文件路径，输出该文件的绝对路径（不落盘） | thread | 输入(`any`:any) | 文件路径(`filepath`:any) |
| 文本输入框 | `text_input` | 提供一个大文本输入框，将其内容作为文本输出给下游（不落盘） | thread | 输入(`any`:any) | 文本(`text`:text) |
| 输入 | `input` | 导入文件或URL | thread | — | 视频(`video`:video); 音频(`audio`:audio); 字幕(`subtitle`:subtitle); URL(`url`:url); 文件路径(`filepath`:any) |
| 输出 | `output` | 导出文件 | thread | 输入(`any`:any) | — |

### 预览节点（`preview`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| 图片对比 | `image_compare` | 叠加对比两张图片：图片2在上、图片1在下，鼠标横向拖动分割线去除上层蒙版，快速对比图形差异；默认上层蒙版只显示右半部，分割线居中 | thread | 图片1（下层）(`image1`:image); 图片2（上层）(`image2`:image) | 图片(`image`:any) |
| 图片预览器 | `image_preview` | 预览图片结果 | thread | 图片(`image`:image); 列表输入(`list`:any) | — |
| 视频预览器 | `video_preview` | 预览视频和字幕，支持标题设置、快捷调整字体大小和位置 | thread | 视频(`video`:video); 译文字幕(`subtitle`:subtitle); 原文字幕(`original`:subtitle); 双语字幕(`bilingual`:subtitle); 列表输入(`list`:any) | — |

### 音频处理节点（`audio`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| 人声分离 | `vocal_separation` | 将音频中的人声和背景音乐分离 | process | 音频(`audio`*:audio) | 人声(`audio`:audio); 背景音乐(`background`:audio) |
| 声音降噪 | `audio_denoise` | 对音频进行智能降噪处理，去除环境噪声、风噪、电流声等干扰 | thread | 音频(`audio`*:audio) | 降噪音频(`audio`:audio) |
| 按照字幕切割音频 | `audio_cut_by_subtitle` | 按 srt 字幕或句子 json 的时间轴切割音频，输出片段清单 json 与各音频片段 | thread | 音频(`audio`*:audio); SRT字幕(`srt`:subtitle); 句子JSON(`json`:json) | 切割信息(`json`:json); 音频片段清单(`audio_segments`:audio_manifest) |
| 配音拼接 | `merge_dub` | 适用于无时间戳要求的纯文本配音片段的合并，按顺序拼接各段配音音频并生成配音字幕 | thread | 音频片段路径(`audio`:audio); 配音任务单JSON(`audio_manifest`:json) | 合并配音音频(`audio`:audio); 配音字幕(`dub_srt`:subtitle) |
| 音视频配音对齐 | `merge_audio` | 基于原视频重新配音后，将配音片段按时间戳对齐到原视频的配音音视频对齐 | thread | 配音任务清单(`audio_manifest`*:json); 输入视频(`video`:video) | 合并音频(`audio`:audio); 配音字幕(`dub_srt`:subtitle); 双语字幕(`dub_bilingual_srt`:subtitle); 调速视频(`video_adjusted`:video) |
| 音轨分离 | `track_separation` | 将音频分离为6轨：人声/贝斯/鼓/吉他/钢琴/其他 | process | 音频(`audio`*:audio) | 人声(`vocals`:audio); 贝斯(`bass`:audio); 鼓(`drums`:audio); 吉他(`guitar`:audio); 钢琴(`piano`:audio); 其他(`other`:audio) |
| 音轨混响 | `track_mix` | 将最多四路音频（主音轨、背景音乐、音轨3、音轨4）按设置的响度、淡入淡出与循环混合后输出。总时长支持「最长」或「以主音轨为准」两种模式。主音轨固定不循环，其余音轨可循环以填充总时长。 | thread | 主音轨(`main_audio`*:audio); 背景音乐(`bgm`:audio); 音轨3(`track3`:audio); 音轨4(`track4`:audio) | 混音结果(`audio`:audio) |
| 音频分离 | `extract_audio` | 从视频中分离提取音频 | thread | 视频(`video`*:video) | 音频(`audio`:audio) |
| 音频素材库 | `audio_asset_library` | 从 URL、本地路径或晴沐配音谷在线素材库ID获取音频素材，自动下载/复制并重命名到当前工作文件夹。 | process | 来源(`any`:any) | 音频文件(`audio`:audio); 文件路径(`path`:filepath) |
| 音频质量转码 | `audio_transcode` | 转换音频格式、采样率、位深、声道和码率 | thread | 音频(`audio`*:audio) | 转码音频(`audio`:audio) |

### 视频处理节点（`video`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| Cutia 交互剪辑 | `cutia` | 将上游素材载入 Cutia，等待手工剪辑并导出成片后继续工作流 | thread | 视频(`video`:video); 音频(`audio`:audio); 图片(`image`:image); 字幕(`subtitle`:subtitle) | 剪辑成片(`video`:video) |
| LCWR 去水印 | `lcwr_watermark_removal` | 调用 LCWR 本地 API 去除视频/图片中的水印与字幕。需先安装并启动 LCWR 软件（下载地址：https://qinmuzhifang.feishu.cn/wiki/IkBVwfe72iEVLTkhVQ0cW0mvnBc），右键「启动LCWR-API.bat」以管理员身份运行本地 API（默认 http://localhost:1120） | process | 视频(`video`:video); 图片(`image`:image) | 视频(`video`:video); 图片(`image`:image) |
| OCR字幕查找 | `subtitle_position_search` | 定位视频字幕区域：支持 OCR 自动查找（输出标注帧与相对坐标 JSON），也可手动框选字幕位置并设置片头片尾跳过时间 | thread | 视频(`video`:video) | 标注帧(`image`:image); 字幕坐标JSON(`json`:json) |
| OCR字幕识别 | `subtitle_recognition` | 按字幕区域坐标用 OCR 识别字幕内容与时间轴，输出 ASR 格式结果 JSON | thread | 视频(`video`*:video); 字幕区域坐标(`json`:json) | 识别结果JSON(ASR)(`subtitle`:json) |
| 在线去水印去字幕 | `online_watermark_removal` | 晴沐智坊提供的在线高质量去除视频中的水印服务，使用前确保注册登录晴沐智坊账号，使用将消耗软件的通用积分，确保积分足够视频消耗，1.3分钱每秒。详情访问晴沐hub：https://www.licorxj.online/capability-hub | thread | 媒体详情JSON(`url_json`:json) | 去水印视频(`video`:video); 任务记录(`json`:json) |
| 字幕烧录 | `merge_sub_video` | 将字幕烧录到视频 | thread | 视频(`video`*:video); 字幕(`subtitle`*:subtitle); 背景音乐(`audio`:audio); 配音音频(`dub`:audio) | 字幕视频(`video`:video) |
| 按字幕切割视频 | `video_cut_by_subtitle` | 按 srt 字幕或句子 json 的时间轴切割视频，输出片段清单 json 与各视频片段 | thread | 视频(`video`*:video); SRT字幕(`srt`:subtitle); 句子JSON(`json`:json) | 切割信息(`json`:json); 视频片段清单(`video_segments`:json) |
| 水印添加 | `watermark` | 为视频添加水印 | thread | 视频(`video`*:video); 水印图片(`image`:image) | 最终视频(`video`:video) |
| 视频切割 | `video_split` | 将视频按数量或时长切割为多段，支持静音点切割 | thread | 视频(`video`*:video); 音频(`audio`:audio) | 切割片段(`video`:video); 切割信息(`text`:text) |
| 视频区域贴片 | `video_region_composite` | 将「视频截取区域」产出的局部视频按坐标贴回主视频。贴片大于区域时自动缩放，主/贴片编码不一致时统一重编码后贴合。 | thread | 主视频(`main_video`*:video); 贴片视频(`patch_video`*:video); 贴片坐标(`patch_json`*:json) | 贴合后视频(`video`:video) |
| 视频截取区域 | `video_region_crop` | 从大分辨率视频中截取指定区域与时段，输出局部视频与坐标 JSON，供「视频区域贴片」节点贴回原视频做局部处理。 | thread | 视频(`video`*:video) | 截取区域视频(`video`:video); 截取坐标(`json`:json) |
| 视频抽帧 | `video_frame_extract` | 从视频指定时间点提取帧图片，支持避开字幕 | thread | 视频(`video`:video); 字幕(`srt`:subtitle) | 帧图片(`image`:image) |
| 视频转码 | `video_transcode` | 使用 ffmpeg 对视频进行转码，支持容器格式、视频/音频编码、码率、分辨率、帧率、编码速度档与像素格式等参数配置 | thread | 视频(`video`*:video) | 转码视频(`video`:video) |
| 音视频合成 | `merge_dub_video` | 将输入音频合成到视频，可设置原视频是否静音、输入音频的响度与淡入淡出。 | thread | 视频(`video`*:video); 音频(`audio`*:audio) | 合成后视频(`video`:video) |

### AI生成类节点（`ai_gen`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| AI封面设计 | `cover` | 根据内容JSON生成封面文生图提示词，支持AI设计和自定义描述两种模式 | thread | 内容JSON(`json`*:json) | 封面提示词(`prompt`:text) |
| AI生图 | `image_gen` | AI图像生成，支持文生图和图生图模式，集成多种生图接口和模型 | process | 文本输入(`text`:text); 图片输入(`image`:image) | 图片列表(`images`:json); 首张图片(`text`:image) |
| AI生视频 | `ai_video_gen` | 根据提示词（文本或txt）、图片/图片列表、音频，调用视频生成接口生成视频；提示词前缀会拼接到连线提示词前 | thread | 提示词(`prompt`:text); 图片/图片列表(`images`:image); 音频(`audio`:audio) | 视频(`videos`:video); 视频(首个)(`video`:video) |
| HyperFrames 渲染 | `hyperframe_render` | 使用 HyperFrames CLI 将 HTML 合成脚本渲染为 MP4 视频 | — | HTML 内容(`html_content`*:text); HTML 文件路径(`html_file`:filepath) | 渲染视频(`video`:video); 渲染结果(`json`:json); 输出信息(`text`:text) |
| Seedream图层拆分 | `seedream_layer` | 调用 Seedream 图层拆分（img2img + layer_decomposition，需 5.0 Pro）：将一张参考图拆为底图与多个图层（含 z_index/名称/bounding_box 坐标），便于二次编辑。 | process | 提示词(`text`:text); 参考图(`image`:image) | 底图(`base`:image); 图层列表(`layers`:list); 坐标数据(`coords`:json) |
| Seedream图生图 | `seedream_img2img` | 调用 Seedream 图生图（img2img）：以一张参考图为基础按提示词重绘生成单张图片。 | process | 提示词(`text`:text); 参考图(`image`:image) | 输出图片列表(`images`:json); 第一张图片(`text`:image) |
| Seedream多图融合 | `seedream_fusion` | 调用 Seedream 多图融合（fusion）：融合多张参考图生成单张图片。支持 image1~image5 共 5 个参考图输入口，按实际连接组装成输入列表。 | process | 提示词(`text`:text); 参考图1(`image1`:image); 参考图2(`image2`:image); 参考图3(`image3`:image); 参考图4(`image4`:image); 参考图5(`image5`:image) | 输出图片列表(`images`:json); 第一张图片(`text`:image) |
| Seedream文生图 | `seedream_txt2img` | 调用火山引擎方舟 Seedream 文生图（txt2img）：根据提示词生成单张图片。支持流式输出与提示词优化，产物保存到 cache/images。 | process | 提示词(`text`:text) | 输出图片列表(`images`:json); 第一张图片(`text`:image) |
| Seedream组图生成 | `seedream_grid` | 调用 Seedream 文生组图（grid / sequential_image_generation）：根据提示词一次生成多张图片。 | process | 提示词(`text`:text) | 输出图片列表(`images`:json); 第一张图片(`text`:image) |
| Seedream联网搜索生图 | `seedream_websearch` | 调用 Seedream 联网搜索生图（websearch / tools=[web_search]）：结合网络搜索结果按提示词生成图片，适合需要真实世界参考的场景。 | process | 提示词(`text`:text) | 输出图片列表(`images`:json); 第一张图片(`text`:image) |
| 即梦-全模态参考生视频 | `seedance_autovideo` | 调用 Seedance 全模态参考生视频（autovideo）：以参考图/视频/音频任意组合生成视频。 | process | 提示词(`text`:text); 参考图(`image`:image); 参考视频(`video`:video); 参考音频(`audio`:audio) | 视频(`video`:video); 视频列表(`videos`:list); 生成参数JSON(`params`:json); 任务ID(`task_id`:text) |
| 即梦-图生视频 | `seedance_img2video` | 调用 Seedance 图生视频-首帧（img2video）：以 1 张参考图为首帧，按提示词生成视频。 | process | 提示词(`text`:text); 参考图(`image`:image) | 视频(`video`:video); 视频列表(`videos`:list); 生成参数JSON(`params`:json); 任务ID(`task_id`:text) |
| 即梦-图生视频(首尾帧) | `seedance_flf2video` | 调用 Seedance 图生视频-首尾帧（flf2video）：以 2 张参考图（首帧/尾帧）生成视频。 | process | 提示词(`text`:text); 参考图1(`image1`:image); 参考图2(`image2`:image) | 视频(`video`:video); 视频列表(`videos`:list); 生成参数JSON(`params`:json); 任务ID(`task_id`:text) |
| 即梦-文生视频 | `seedance_txt2video` | 调用火山方舟 Seedance 文生视频（txt2video）：根据提示词生成视频。支持异步任务轮询、优先历史记录与查询进度。 | process | 提示词(`text`:text) | 视频(`video`:video); 视频列表(`videos`:list); 生成参数JSON(`params`:json); 任务ID(`task_id`:text) |
| 图片蒙版 | `image_mask` | 上游输入图片，在卡片上用画笔/矩形绘制蒙版，后端合成蒙版图并输出蒙版合成图与黑白蒙版 | thread | 图片(`image`:image) | 蒙版合成图(`image`:image); 蒙版(`mask`:image) |
| 语音合成 (TTS) | `tts` | 文本转语音，支持多种TTS模式 | process | TTS任务单JSON(`text`*:json); TTS任务表(`pandas`:pandas); 原始音频(切割参考)(`source_audio`:audio) | TTS任务单JSON(`text`:json); TTS任务表(`pandas`:pandas) |
| 通用LLM请求 | `llm_request` | 通用 LLM 请求，支持文本/图片输入，可配置 prompt、模型、温度等 | process | 文本输入(`text`:text); 图片输入(`image`:image); JSON输入(`json`:json) | 结果文件(`result`:json); 文本结果(`text`:text) |

### 翻译相关节点（`translation`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| AI字幕纠错 | `ai_subtitle_correct` | 读取 ASR JSON，按字数上限切分后请求 LLM（vlf-02）修复识别错误、去除空格并修正标点；专有名词可辅助识别。prompt 可在 Prompt 工程中修改。 | llm | ASR JSON(`json`:json) | ASR JSON(`output`:json); 纠错全文TXT(`text`:text) |
| AI标点补全 | `ai_punctuate` | 读取 ASR 结果 JSON，对识别全文进行 LLM 标点修复，支持按字数上限分批与上下文重叠处理 | llm | ASR JSON(`json`:json) | ASR JSON(`output`:json); 修复全文TXT(`text`:text) |
| ASR后处理 | `asr_postprocess` | 对上游 ASR 结果执行 VAD断句 / 时间戳对齐 / 说话人识别 / 标点恢复，可逐阶段勾选并单独选择模型 | process | ASR结果JSON(`subtitle`*:json); ASR音源(`asr_audio`:audio); 人声音源(`vocal_audio`:audio); 对齐音源(`alignment_audio`:audio) | 后处理结果JSON(`subtitle`:json) |
| ASR结果校验 | `asr_result_validate` | 校验 ASR JSON 中 text / segments / words 的一致性：先校验 text 与压平 segments（去标点空格后顺序匹配），再校验压平 segments 与压平 words。校验通过则原样透传输出，不通过则抛出错误并指明错误点。 | thread | ASR结果JSON(`json`*:json) | ASR结果JSON(透传)(`json`:json) |
| ASR识别 | `asr_recognize` | 仅执行语音识别（不执行后处理），输出原始识别结果供下游 ASR后处理 节点继续处理 | process | ASR音源(`asr_audio`*:audio); 人声音源(`vocal_audio`:audio) | ASR识别结果JSON(`subtitle`:json) |
| 内容总结 | `summarize` | 总结上下文、提取术语表 | process | 句子文本(`text`*:text) | 总结结果JSON(`subtitle`:json) |
| 句子分割 | `sentence_split` | 将ASR结果按标点和长度分割为独立句子，保留单词级时间戳 | thread | ASR结果JSON(`subtitle`*:json) | 分割结果JSON(`subtitle`:json); 句子文本(`text`:text) |
| 字幕生成 | `subtitle_gen` | 兼容句子分割、逐句翻译、双语对齐结果并生成字幕文件 | thread | 句子/翻译/对齐JSON(`subtitle`*:json) | 译文字幕(`subtitle`:subtitle); 原文字幕(`original`:subtitle); 双语字幕(`bilingual`:subtitle) |
| 断句预处理 | `sentence_preprocess` | 基于全文文本（ASR JSON 或长文本 TXT）按 ASR分段/标点符号/AI 三种方法重新断句，生成更可靠的初始 segments，可选重建句子级时间戳 | thread | ASR结果JSON(`json`:json); 长文本TXT(`text`:text) | 断句预处理JSON(`subtitle`:json); 词级时间戳表(`word_index`:json) |
| 生成配音任务 | `dub_task` | 将带时间戳的句子 JSON 包装为可编辑的 TTS 任务单 | thread | 句子时间戳JSON(`subtitle`:json); 文本文件(`text_file`:text) | TTS任务单JSON(`text`:json); TTS任务表(`pandas`:pandas) |
| 翻译项目名称 | `translate_task_name` | 将项目名称翻译为目标语言，可选择是否用译文替换任务名称 | thread | 输入(`input`:any) | 翻译结果(`text`:text) |
| 译文断句和双语对齐 | `subtitle_align` | 对超长译文进行断句并与原文对齐，调整时间戳 | thread | 翻译结果JSON(`subtitle`*:json) | 对齐结果JSON(`subtitle`:json) |
| 语音识别 (ASR) | `asr` | 从音频/视频中提取文字，支持 WhisperX / Qwen3-ASR 等引擎 | process | ASR音源(`asr_audio`*:audio); 人声音源(`vocal_audio`:audio) | ASR结果JSON(`subtitle`:json) |
| 逐句翻译 | `translate` | AI驱动的高质量翻译 | process | 切割句子JSON(`subtitle`*:json); 总结结果JSON(`summary`:json) | 直译结果JSON(`subtitle`:json); 反思翻译JSON(`reflect`:json) |

### AIGC流程链（`aigc`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| ComfyUI 生图 | `aigc_comfyui` | 调用本地/局域网 ComfyUI 实例运行工作流，支持文生图/图生图，参数来自「其他能力接口」设置 | thread | 提示词(`text`:text); 参考视频(`reference_video`:video); 首帧(`first_frame`:image); 图片2(`image2`:image); 图片3(`image3`:image); 图片4(`image4`:image); 尾帧(`last_frame`:image) | 产物列表(`images`:any); 第一个产物(`first`:any); 全部产物(`files`:any) |
| RunningHub 生成 | `aigc_runninghub` | 调用 RunningHub OpenAPI 运行工作流或 AI 应用，生成图片/视频，参数来自「其他能力接口」设置 | process | 提示词(`text`:text); 参考视频(`reference_video`:video); 首帧(`first_frame`:image); 图片2(`image2`:image); 图片3(`image3`:image); 图片4(`image4`:image); 尾帧(`last_frame`:image) | 产物列表(`images`:any); 第一个产物(`first`:any); 全部产物(`files`:any) |
| 即梦 CLI 生成 | `aigc_jimeng` | 通过本地即梦(dreamina) CLI 生成图片或视频，支持文生图/图生图/文生视频/图生视频/首尾帧视频 | process | 提示词(`text`:text); 参考视频(`reference_video`:video); 首帧(`first_frame`:image); 图片2(`image2`:image); 图片3(`image3`:image); 图片4(`image4`:image); 尾帧(`last_frame`:image) | 产物列表(`images`:any); 第一个产物(`first`:any); 全部产物(`files`:any) |

### 智能体（`agent`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| 剪辑AI Agent | `editor_agent` | 通过自然语言读取并修改当前任务的剪辑项目和时间线 | process | 编辑指令(`text`:text) | 剪辑项目(`project`:json); 运行记录(`artifacts`:json); 执行结果(`result`:text) |
| 小pi通用智能体 | `pi_agent` | 将小 Pi 以工作流节点方式嵌入工作流：注入任务背景与输入输出契约，发起一次 Pi 会话并执行任务，产物保存到任务 cache 目录 | process | 输入1(`input_1`:any); 输入2(`input_2`:any) | 输出1(`output_1`:any); 输出2(`output_2`:any) |

### 流程控制节点（`flow_control`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| 定时执行 | `timed_delay` | 等待指定时间后继续执行，支持时间点和倒计时两种模式 | thread | 输入(`any`:any) | 输出(`any`:any) |
| 运行等待 | `run_wait` | 开启后等待指定时长，超时抛出等待超时错误结束工作流；关闭则跳过并透传输入 | thread | 输入(`input`:any) | 输出(`output`:any) |

### 网络请求类节点（`network_request`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| QM虚拟邮箱 | `qm_virtual_mailbox` | 通过晴沐智坊虚拟邮箱，向已验证的转发目标发送验证码邮件。费用2分钱/条（云端处理）。使用前请确保已在网页端设置并验证转发目标。详情访问：https://www.licorxj.online/mail-forwarding | thread | 文本内容(`text`:text) | 发送结果(`json`:json) |
| 媒体转链接 | `media_to_url` | 上传本地视频/图片到腾讯云 VOD，返回 URL 及完整媒体详情（尺寸/时长/码率等）保存为 JSON | thread | 视频(`video`:video); 图片(`image`:image) | 媒体详情(`json`:json) |
| 平台视频下载 | `platform_download` | 使用 yt-dlp 下载平台视频 | process | URL(`url`*:url) | 视频(`video`:video); 字幕(`subtitle`:subtitle); 封面(`image`:image) |
| 网络请求 | `http_request` | 执行可配置的 HTTP 网络请求，支持请求体占位符、重试和响应保存 | process | 输入 1(`input_1`:any); 输入 2(`input_2`:any); 输入 3(`input_3`:any); 请求 Data(`request_data`:json) | 结果文件(`result`:any); JSON 结果(`json`:json); 文本结果(`text`:text); 状态码(`status`:text) |

### 工具类节点（`utility`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| JSON可视化编辑 | `json_visual_editor` | 可视化编辑 JSON，默认透传，可另存副本 | thread | JSON(`json`*:json) | JSON(`json`:json) |
| JSON编辑 | `json_editor` | 按key表达式修改JSON中指定字段的值，覆盖保存原文件 | thread | JSON(`json`:json); 修改值(`text`:text) | JSON(`json`:json) |
| JSON转文本 | `json_to_text` | 将JSON转换为文本文件，支持全量转文本或按key表达式取值 | thread | JSON(`json`:json) | 文本文件(`text`:text) |
| SRT字幕转json | `srt_to_json` | 将 SRT 字幕转换为 ASR 结果格式 JSON（包含 text 与 segments，不生成词级时间戳 words），可直接接入 ASR 结果校验、预处理等下游节点。输入为「字幕」类型，可连线「字幕生成」等字幕节点的输出（默认输出 .srt）。 | thread | 字幕(`subtitle`*:subtitle) | ASR结果JSON(`json`:json) |
| SRT转文本 | `srt_to_text` | 将 SRT 字幕直接转换为纯文本：去掉序号与时间轴，提取每条字幕的文本内容，按原顺序拼接为 .txt 文本文件输出。输入为「字幕」类型，可连线「字幕生成」等字幕节点的输出（默认输出 .srt）。 | thread | 字幕(`subtitle`*:subtitle) | 文本(`text`:text) |
| 字幕编辑 | `subtitle_editor` | 逐条编辑字幕（文本/时间/合并/拆分），带视频预览，默认透传，可另存副本 | thread | 字幕(`subtitle`*:subtitle) | 字幕(`subtitle`:subtitle) |
| 文本编辑 | `text_editor` | 可视化编辑文本，支持查找删除/替换/正则，默认透传，可另存副本 | thread | 文本(`text`*:text) | 文本(`text`:text) |
| 视频发布 | `video_publish` | 将视频发布到指定社交平台，支持多平台分发、定时发布、草稿模式 | process | 视频(`video`*:video); 横屏封面(`cover_landscape`:image); 竖屏封面(`cover_portrait`:image); 标题/描述(`json`:json) | 发布结果(`text`:text); 结果文件(`result_file`:file) |
| 输出合并为列表 | `output_merge_list` | 将多个上游节点的输出（文本或路径）合并为列表格式 JSON，内存传递、不落盘；输入端口数量可在卡片上动态加减 | thread | — | 列表JSON(`json`:json) |

### 文件操作类节点（`file`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| 取文件路径 | `resolve_path` | 以相对路径拼接出项目文件夹内的特定文件路径 | thread | 输入(`input`:any) | 路径(`output`:any) |
| 文件改名 | `file_rename` | 给输入文件改名，支持自定义文件名、前缀、后缀方式 | thread | 输入(`any`*:any) | 输出(`any`:any) |
| 路径转标题 | `path_to_title` | 从文件路径提取组件并拼装标题 | thread | 输入(`any`:any) | 标题(`text`:text) |

### 组合节点（`group_node`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| 组合 | `groupnode_mtbj91n4` | 组合（组合节点） | — | ASR后处理 / 对齐音源(`gin_1`:audio); ASR后处理 / 人声音源(`gin_2`:audio); 语音识别 (ASR) / ASR音源(`gin_3`:audio) | — |
| 组合 | `groupnode_mtbj9s8i` | 组合（组合节点） | — | ASR后处理 / 对齐音源(`gin_1`:audio); ASR后处理 / 人声音源(`gin_2`:audio); 语音识别 (ASR) / ASR音源(`gin_3`:audio) | — |
