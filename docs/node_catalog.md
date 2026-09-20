# VideoLingo 节点目录（Node Catalog）

> 自动生成时间：2026-09-20 09:26:47  
> 节点总数：153　（带 `*` 的接口为必填项）

## 总览

| 分组 | 节点数 |
|------|-------|
| 输入输出节点（`io`） | 5 |
| 预览节点（`preview`） | 3 |
| 音频处理节点（`audio`） | 10 |
| 视频处理节点（`video`） | 18 |
| AI生成类节点（`ai_gen`） | 20 |
| 翻译相关节点（`translation`） | 15 |
| 漫剧·剧本链（`agi_story`） | 4 |
| 漫剧·资产链（`agi_asset`） | 6 |
| 漫剧·分镜链（`agi_shot`） | 4 |
| 漫剧·成片链（`agi_render`） | 2 |
| 漫剧·数据链（`agi_data`） | 3 |
| AIGC流程链（`aigc`） | 4 |
| 智能体（`agent`） | 3 |
| 流程控制节点（`flow_control`） | 6 |
| 网络请求类节点（`network_request`） | 7 |
| 工具类节点（`utility`） | 11 |
| 文件操作类节点（`file`） | 3 |
| 组合节点（`group_node`） | 3 |
| asset（`asset`） | 7 |
| cutia（`cutia`） | 4 |
| hyperframes（`hyperframes`） | 5 |
| music_gen（`music_gen`） | 10 |

## 节点详情

### 输入输出节点（`io`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| 产物文件归档 | `archive_artifacts` | 将上游多个产物文件归档到指定目录，支持复制/剪切、新建子文件夹、重命名与自动序号 | thread | 产物输入(`any`:any) | 归档路径(`output`:any) |
| 文件加载 | `file_load` | 在卡片上选择或输入文件路径，输出该文件的绝对路径（不落盘） | thread | 输入(`any`:any) | 文件路径(`filepath`:any) |
| 文本输入框 | `text_input` | 提供一个大文本输入框，将其内容作为文本输出给下游（不落盘） | thread | 输入(`any`:any) | 文本(`text`:text) |
| 输入 | `input` | 导入文件或URL | thread | — | 视频(`video`:video); 音频(`audio`:audio); 字幕(`subtitle`:subtitle); URL(`url`:url); 文件路径(`filepath`:any); 文本(`text`:text); 不需要输入(`no_input`:any) |
| 输出 | `output` | 导出文件 | thread | 输入(`any`:any) | — |

### 预览节点（`preview`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| 图片对比 | `image_compare` | 叠加对比两张图片：图片2在上、图片1在下，鼠标横向拖动分割线去除上层蒙版，快速对比图形差异；默认上层蒙版只显示右半部，分割线居中 | thread | 图片1（下层）(`image1`:any); 图片2（上层）(`image2`:any) | 图片(`image`:any) |
| 图片预览器 | `image_preview` | 预览图片结果 | thread | 图片(`image`:image); 列表输入(`list`:any) | — |
| 视频预览器 | `video_preview` | 预览视频和字幕，支持标题设置、快捷调整字体大小和位置 | thread | 视频(`video`:video); 译文字幕(`subtitle`:subtitle); 原文字幕(`original`:subtitle); 双语字幕(`bilingual`:subtitle); 列表输入(`list`:any) | — |

### 音频处理节点（`audio`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| 人声分离 | `vocal_separation` | 将音频中的人声和背景音乐分离 | process | 音频(`audio`*:audio) | 人声(`audio`:audio); 背景音乐(`background`:audio) |
| 声音降噪 | `audio_denoise` | 对音频进行智能降噪处理，去除环境噪声、风噪、电流声等干扰 | thread | 音频(`audio`*:audio) | 降噪音频(`audio`:audio) |
| 按照字幕切割音频 | `audio_cut_by_subtitle` | 按 srt 字幕或句子 json 的时间轴切割音频，输出片段清单 json 与各音频片段 | thread | 音频(`audio`*:audio); SRT字幕(`srt`:subtitle); 句子JSON(`json`:json) | 切割信息(`json`:json); 音频片段清单(`audio_segments`:audio_manifest) |
| 配音拼接 | `merge_dub` | 适用于无时间戳要求的纯文本配音片段的合并，按顺序拼接各段配音音频并生成配音字幕 | thread | 音频片段路径(`audio`:audio); 配音任务单JSON(`audio_manifest`:json) | 合并配音音频(`audio`:audio); 配音字幕(`dub_srt`:subtitle) |
| 配音片段合并对齐 | `merge_audio` | 基于原视频重新配音后，将配音片段按时间戳对齐到原视频的配音音视频对齐 | thread | 配音任务清单(`audio_manifest`*:json); 输入视频(`video`:video) | 合并音频(`audio`:audio); 配音字幕(`dub_srt`:subtitle); 双语字幕(`dub_bilingual_srt`:subtitle); 调速视频(`video_adjusted`:video) |
| 音轨分离 | `track_separation` | 将音频分离为6轨：人声/贝斯/鼓/吉他/钢琴/其他 | process | 音频(`audio`*:audio) | 人声(`vocals`:audio); 贝斯(`bass`:audio); 鼓(`drums`:audio); 吉他(`guitar`:audio); 钢琴(`piano`:audio); 其他(`other`:audio) |
| 音轨混响 | `track_mix` | 将最多四路音频（主音轨、背景音乐、音轨3、音轨4）按设置的响度、淡入淡出与循环混合后输出。总时长支持「最长」或「以主音轨为准」两种模式。主音轨固定不循环，其余音轨可循环以填充总时长。 | thread | 主音轨(`main_audio`*:audio); 背景音乐(`bgm`:audio); 音轨3(`track3`:audio); 音轨4(`track4`:audio) | 混音结果(`audio`:audio) |
| 音频分离 | `extract_audio` | 从视频中分离提取音频 | thread | 视频(`video`*:video) | 音频(`audio`:audio) |
| 音频增强 | `audio_enhance` | 通过音频增强接口/模型处理音频（去混响、降噪、音质增强），输出增强后的音频 | process | 音频(`audio`*:audio) | 增强音频(`audio`:audio); 残差/副产物(`background`:audio); 第三路输出(`extra`:audio) |
| 音频质量转码 | `audio_transcode` | 转换音频格式、采样率、位深、声道和码率 | thread | 音频(`audio`*:audio) | 转码音频(`audio`:audio) |

### 视频处理节点（`video`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| LCWR 去水印 | `lcwr_watermark_removal` | 调用 LCWR 本地 API 去除视频/图片中的水印与字幕。需先安装并启动 LCWR 软件（下载地址：https://qinmuzhifang.feishu.cn/wiki/IkBVwfe72iEVLTkhVQ0cW0mvnBc），右键「启动LCWR-API.bat」以管理员身份运行本地 API（默认 http://localhost:1120） | process | 视频(`video`:video); 图片(`image`:image) | 视频(`video`:video); 图片(`image`:image) |
| OCR字幕查找 | `subtitle_position_search` | 定位视频字幕区域：支持 OCR 自动查找（输出标注帧与相对坐标 JSON），也可手动框选字幕位置并设置片头片尾跳过时间 | thread | 视频(`video`:video) | 标注帧(`image`:image); 字幕坐标JSON(`json`:json) |
| OCR字幕识别 | `subtitle_recognition` | 按字幕区域坐标用 OCR 识别字幕内容与时间轴，输出 ASR 格式结果 JSON | thread | 视频(`video`*:video); 字幕区域坐标(`json`:json) | 识别结果JSON(ASR)(`subtitle`:json) |
| 切割片头片尾 | `video_clip_intro_outro` | 从主视频中裁剪片头与片尾，输出裁剪后的主视频、片头片段、片尾片段（ffmpeg 流拷贝，不重新编码） | thread | 主视频(`video`*:video) | 裁剪后主视频(`video`:video); 片头片段(`intro`:video); 片尾片段(`outro`:video) |
| 在线去水印去字幕 | `online_watermark_removal` | 晴沐智坊提供的在线高质量去除视频中的水印服务，使用前确保注册登录晴沐智坊账号，使用将消耗软件的通用积分，确保积分足够视频消耗，1.3分钱每秒。详情访问晴沐hub：https://www.licorxj.online/capability-hub | thread | 媒体详情JSON(`url_json`:json) | 去水印视频(`video`:video); 任务记录(`json`:json) |
| 字幕烧录 | `merge_sub_video` | 将字幕烧录到视频 | thread | 视频(`video`*:video); 字幕(`subtitle`*:subtitle); 背景音乐(`audio`:audio); 配音音频(`dub`:audio) | 字幕视频(`video`:video) |
| 按字幕切割视频 | `video_cut_by_subtitle` | 按 srt 字幕或句子 json 的时间轴切割视频，输出片段清单 json 与各视频片段 | thread | 视频(`video`*:video); SRT字幕(`srt`:subtitle); 句子JSON(`json`:json) | 切割信息(`json`:json); 视频片段清单(`video_segments`:json) |
| 水印添加 | `watermark` | 为视频添加水印 | thread | 视频(`video`*:video); 水印图片(`image`:image) | 最终视频(`video`:video) |
| 添加素材到剪辑 | `add_media_to_library` | 将任意类型素材注册到剪辑工作台的素材库（不写入时间线轨道），供后续剪辑操作调用 | thread | 剪辑项目(`project`:json); 素材(`media`:any) | 剪辑项目(`project`:json) |
| 视频切割 | `video_split` | 将视频按数量或时长切割为多段，支持静音点切割 | thread | 视频(`video`*:video); 音频(`audio`:audio) | 切割片段(`video`:video); 切割信息(`text`:text) |
| 视频区域贴片 | `video_region_composite` | 将「视频截取区域」产出的局部视频按坐标贴回主视频。贴片大于区域时自动缩放，主/贴片编码不一致时统一重编码后贴合。 | thread | 主视频(`main_video`*:video); 贴片视频(`patch_video`*:video); 贴片坐标(`patch_json`*:json) | 贴合后视频(`video`:video) |
| 视频去重 | `video_dedupe` | 反平台查重变换：对视频做水平镜像、放大裁切、调速、调色/滤镜、加边框等画面变换以规避重复检测；不删内容，只改画面（ffmpeg 重编码） | thread | 视频(`video`*:video) | 去重视频(`video`:video) |
| 视频截取区域 | `video_region_crop` | 从大分辨率视频中截取指定区域与时段，输出局部视频与坐标 JSON，供「视频区域贴片」节点贴回原视频做局部处理。 | thread | 视频(`video`*:video) | 截取区域视频(`video`:video); 截取坐标(`json`:json) |
| 视频抽帧 | `video_frame_extract` | 从视频指定时间点提取帧图片，支持避开字幕 | thread | 视频(`video`:video); 字幕(`srt`:subtitle) | 帧图片(`image`:image) |
| 视频拼接 | `video_concat` | 将主视频/片段1~3/封面图按设定顺序与缩放方式一次性拼装为单个视频，封面图可选插入开头或结尾。 | thread | 主视频(`main`:video); 片段1(`segment1`:video); 片段2(`segment2`:video); 片段3(`segment3`:video); 封面图(`cover`:image) | 拼接视频(`video`:video) |
| 视频缩放 | `video_scale` | 使用 ffmpeg 将视频缩放到预置分辨率（按目标高度等比缩放）或自定义宽高，支持输出容器格式与编码质量（CRF）设置 | thread | 视频(`video`*:video) | 缩放后视频(`video`:video) |
| 视频转码 | `video_transcode` | 使用 ffmpeg 对视频进行转码，支持容器格式、视频/音频编码、码率、分辨率、帧率、编码速度档与像素格式等参数配置 | thread | 视频(`video`*:video) | 转码视频(`video`:video) |
| 音视频合成 | `merge_dub_video` | 将输入音频合成到视频，可设置原视频是否静音、输入音频的响度与淡入淡出。 | thread | 视频(`video`*:video); 音频(`audio`*:audio) | 合成后视频(`video`:video) |

### AI生成类节点（`ai_gen`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| AI封面设计 | `cover` | 根据内容JSON生成封面文生图提示词，支持AI设计和自定义描述两种模式 | thread | 内容JSON(`json`*:json) | 封面提示词(`prompt`:text) |
| AI生图 | `image_gen` | AI图像生成，支持文生图和图生图模式，集成多种生图接口和模型 | process | 文本输入(`text`:text); 图片输入(`image`:image); 分辨率(`resolution`:text); 比例(`aspect_ratio`:text) | 图片列表(`images`:json); 首张图片(`text`:image) |
| AI生视频 | `ai_video_gen` | 根据提示词（文本或txt）、图片/图片列表、音频，调用视频生成接口生成视频；提示词前缀会拼接到连线提示词前 | thread | 提示词(`prompt`:text); 图片/图片列表(`images`:image); 音频(`audio`:audio) | 视频(`videos`:video); 视频(首个)(`video`:video); 尾帧(`last_frame`:image) |
| Seedream图层拆分 | `seedream_layer` | 调用 Seedream 图层拆分（img2img + layer_decomposition，需 5.0 Pro）：将一张参考图拆为底图与多个图层（含 z_index/名称/bounding_box 坐标），便于二次编辑。 | process | 提示词(`text`:text); 参考图(`image`:image) | 底图(`base`:image); 图层列表(`layers`:list); 坐标数据(`coords`:json) |
| Seedream图生图 | `seedream_img2img` | 调用 Seedream 图生图（img2img）：以一张参考图为基础按提示词重绘生成单张图片。 | process | 提示词(`text`:text); 参考图(`image`:image) | 输出图片列表(`images`:json); 第一张图片(`text`:image) |
| Seedream多图融合 | `seedream_fusion` | 调用 Seedream 多图融合（fusion）：融合多张参考图生成单张图片。支持 image1~image5 共 5 个参考图输入口，按实际连接组装成输入列表。 | process | 提示词(`text`:text); 参考图1(`image1`:image); 参考图2(`image2`:image); 参考图3(`image3`:image); 参考图4(`image4`:image); 参考图5(`image5`:image) | 输出图片列表(`images`:json); 第一张图片(`text`:image) |
| Seedream文生图 | `seedream_txt2img` | 调用火山引擎方舟 Seedream 文生图（txt2img）：根据提示词生成单张图片。支持流式输出与提示词优化，产物保存到 cache/images。 | process | 提示词(`text`:text) | 输出图片列表(`images`:json); 第一张图片(`text`:image) |
| Seedream组图生成 | `seedream_grid` | 调用 Seedream 文生组图（grid / sequential_image_generation）：根据提示词一次生成多张图片。 | process | 提示词(`text`:text) | 输出图片列表(`images`:json); 第一张图片(`text`:image) |
| Seedream联网搜索生图 | `seedream_websearch` | 调用 Seedream 联网搜索生图（websearch / tools=[web_search]）：结合网络搜索结果按提示词生成图片，适合需要真实世界参考的场景。 | process | 提示词(`text`:text) | 输出图片列表(`images`:json); 第一张图片(`text`:image) |
| 即梦-全模态参考生视频 | `seedance_autovideo` | 调用 Seedance 全模态参考生视频（autovideo）：以参考图/视频/音频任意组合生成视频。 | process | 提示词(`text`:text); 参考图列表(`image`:list); 参考视频(`video`:video); 参考音频(`audio`:audio) | 视频(`video`:video); 视频列表(`videos`:list); 尾帧(`last_frame`:image); 生成参数JSON(`params`:json); 任务ID(`task_id`:text) |
| 即梦-图生视频 | `seedance_img2video` | 调用 Seedance 图生视频-首帧（img2video）：以 1 张参考图为首帧，按提示词生成视频。 | process | 提示词(`text`:text); 参考图(`image`:image) | 视频(`video`:video); 视频列表(`videos`:list); 尾帧(`last_frame`:image); 生成参数JSON(`params`:json); 任务ID(`task_id`:text) |
| 即梦-图生视频(首尾帧) | `seedance_flf2video` | 调用 Seedance 图生视频-首尾帧（flf2video）：以 2 张参考图（首帧/尾帧）生成视频。 | process | 提示词(`text`:text); 参考图1(`image1`:image); 参考图2(`image2`:image) | 视频(`video`:video); 视频列表(`videos`:list); 尾帧(`last_frame`:image); 生成参数JSON(`params`:json); 任务ID(`task_id`:text) |
| 即梦-文生视频 | `seedance_txt2video` | 调用火山方舟 Seedance 文生视频（txt2video）：根据提示词生成视频。支持异步任务轮询、优先历史记录与查询进度。 | process | 提示词(`text`:text) | 视频(`video`:video); 视频列表(`videos`:list); 尾帧(`last_frame`:image); 生成参数JSON(`params`:json); 任务ID(`task_id`:text) |
| 图声生视频-kie | `kie_image_audio_to_video` | 用图片 + 声音驱动生成视频（数字人 / 对口型 / 角色演绎）。image1 为必填主图，kling-3.0/video 额外支持 image2~image5 共 5 张参考图；audio 输入口接驱动音频；提示词可来自连线文本或节点内填写。使用前请先注册 KIE 账号并获取 API Key：点击卡片上方「获取key」前往官网注册，拿到 Key 后填入【全局设置 → 密钥管理器】，密钥名称必须为 KIEAI_API_KEY（也可在系统环境变量中设置同名变量）；用量见「用量日志」。 | process | 主图片(`image1`*:image); 参考图2(`image2`:image); 参考图3(`image3`:image); 参考图4(`image4`:image); 参考图5(`image5`:image); 驱动音频(`audio`*:audio); 提示词(`text`:text) | 生成视频(`video`:video); 视频列表(`videos`:json); 生成参数JSON(`params`:json) |
| 图片蒙版 | `image_mask` | 上游输入图片，在卡片上用画笔/矩形绘制蒙版，后端合成蒙版图并输出蒙版合成图与黑白蒙版 | thread | 图片(`image`:image) | 蒙版合成图(`image`:image); 蒙版(`mask`:image) |
| 图片高清放大-kie | `kie_image_upscale` | 调用 KIE AI 对图片做高清放大。使用前请先注册 KIE 账号并获取 API Key：点击卡片上方「获取key」前往官网注册，拿到 Key 后填入【全局设置 → 密钥管理器】，密钥名称必须为 KIEAI_API_KEY（也可在系统环境变量中设置同名变量）；调用量与扣费明细可点击「用量日志」查看。 | process | 待放大图片(`image`*:image) | 放大后图片(`image`:image); 图片列表(`images`:json); 处理参数JSON(`params`:json) |
| 视频对口型-kie | `kie_lip_sync` | 调用 KIE AI 让视频人物口型匹配目标音频（视频 + 音频 → 对口型视频）。使用前请先注册 KIE 账号并获取 API Key：点击卡片上方「获取key」前往官网注册，拿到 Key 后填入【全局设置 → 密钥管理器】，密钥名称必须为 KIEAI_API_KEY（也可在系统环境变量中设置同名变量）；调用量与扣费明细可点击「用量日志」查看。 | process | 待对口型视频(`video`*:video); 目标音频(`audio`*:audio) | 对口型视频(`video`:video); 视频列表(`videos`:json); 处理参数JSON(`params`:json) |
| 视频高清放大-kie | `kie_video_upscale` | 调用 KIE AI 对视频做高清放大。使用前请先注册 KIE 账号并获取 API Key：点击卡片上方「获取key」前往官网注册，拿到 Key 后填入【全局设置 → 密钥管理器】，密钥名称必须为 KIEAI_API_KEY（也可在系统环境变量中设置同名变量）；调用量与扣费明细可点击「用量日志」查看。 | process | 待放大视频(`video`*:video) | 放大后视频(`video`:video); 视频列表(`videos`:json); 处理参数JSON(`params`:json) |
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
| 译文断句和双语对齐 | `subtitle_align` | 对超长译文进行断句并与原文对齐，调整时间戳 | thread | asr格式json(`asr`*:json); 翻译结果JSON(`subtitle`*:json) | 对齐结果JSON(`subtitle`:json) |
| 语音识别 (ASR) | `asr` | 从音频/视频中提取文字，支持 WhisperX / Qwen3-ASR 等引擎 | process | ASR音源(`asr_audio`*:audio); 人声音源(`vocal_audio`:audio) | ASR结果JSON(`subtitle`:json) |
| 逐句翻译 | `translate` | AI驱动的高质量翻译 | process | 切割句子JSON(`subtitle`*:json); 总结结果JSON(`summary`:json) | 直译结果JSON(`subtitle`:json); 反思翻译JSON(`reflect`:json) |
| 配音审听及微调 | `dub_visual_check` | 读取上游配音任务 JSON，打开审听页面逐句试听与微调：可修改朗读文本/指令、更换参考音频、按语速重生单条或批量重生；本节点把上游输入 JSON 透传到输出（json），可选等待审听完成后再继续下游。 | thread | 配音任务JSON(`json`:json) | 配音任务JSON(`json`:json) |

### 漫剧·剧本链（`agi_story`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| 分镜剧本 | `agi_shot` | AI 漫剧·分镜剧本：为章节生成分镜（出场人物/场景/对话/音效设计）并写入 | thread | 章节ID(`chapter_id`:any); 分镜指引(`text`:text) | 章节ID(`chapter_id`:text); 分镜ID列表(`shot_ids`:json); 分镜内容(`shots`:json) |
| 剧本深化 | `agi_deepen` | AI 漫剧·剧本深化：把项目骨架深化为严格格式化的设定书并入库——剧本简介、各章节内容规划(建章)、人物设计提炼(同名提炼/新增)、画风元素锁定(写入骨架供下游生图取用) | thread | 创作项目ID(`creation_id`:any); 额外要求(`text`:text) | 创作项目ID(`creation_id`:text); 剧本设定书(`bible`:json); 剧本简介(`synopsis`:text); 画风锁定(`style_bible`:text) |
| 章节剧本 | `agi_chapter` | AI 漫剧·章节剧本：为创作项目生成若干章节（标题/原文/简述）并写入 | thread | 创作项目ID(`creation_id`:any); 章节指引(`text`:text) | 创作项目ID(`creation_id`:text); 章节ID(`chapter_id`:text); 章节ID列表(`chapter_ids`:json); 章节内容(`chapters`:json) |
| 项目立项·剧本创作 | `agi_project` | AI 漫剧·起始节点：创建创作项目并用 LLM 打好故事骨架（世界观/大纲/总剧本），产出 creation_id 贯穿下游全部节点 | thread | 创意/要求(`text`:text) | 创作项目ID(`creation_id`:text); 项目骨架(`project`:json) |

### 漫剧·资产链（`agi_asset`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| 人物资产创作 | `agi_character` | AI 漫剧·人物资产创作：用 LLM 生成人物设定并写入创作项目，可发布到公共角色库并生成多视角图 | thread | 创作项目ID(`creation_id`:any); 创意简介(`text`:text) | 创作项目ID(`creation_id`:text); 人物设定(`characters`:json); 角色立绘(`images`:any) |
| 人物音色生产 | `agi_voice` | AI 漫剧·人物音色生产：按「生成对象」为目标人物一次性设计 15~25 字台词，分别调用设计与克隆 TTS 接口合成音色样本，登记到配音谷音色库（vf:voices 引用）并绑定人物 voice_ref，打通分镜配音的音色克隆链路 | process | 创作项目ID(`creation_id`:any) | 创作项目ID(`creation_id`:text); 音色清单(`voices`:json); 样本音频(`audio`:audio); 失败清单(`failed`:json) |
| 场景资产创作 | `agi_scene` | AI 漫剧·场景资产创作：生成关键场景(地点/时间段/光影)并生成固定视角概念图，写入场景资产表并登记 scene_image 资产 | process | 创作项目ID(`creation_id`:any); 补充描述(`text`:text) | 创作项目ID(`creation_id`:text); 场景ID列表(`scene_ids`:json); 场景清单(`scenes`:json); 场景图(`images`:any) |
| 生成提示词 | `agi_prompt` | AI 漫剧·生成提示词：把资产描述结合整体画风生成 final_prompt 写入库（可调试/可人工改），供生图节点使用；资产类型选「分镜」时生成 image_prompt/video_prompt 供首尾帧与生视频节点消费 | thread | 创作项目ID(`creation_id`:any); 资产ID列表(可选)(`ids`:json); 章节ID(分镜用)(`chapter_id`:text); 多章节ID列表(分镜用)(`chapter_ids`:json) | 创作项目ID(`creation_id`:text); 资产类型(`asset_type`:text); 资产ID列表(`ids`:json); 提示词结果(`final_prompts`:json) |
| 资产自动提取 | `agi_extract` | AI 漫剧·资产自动提取：从格式化剧本一次性提取人物/场景/道具，按名去重入库（同名复用更新，新增写入一级资产表），对标 Drama extractor | thread | 创作项目ID(`creation_id`:any); 补充剧本(`text`:text) | 创作项目ID(`creation_id`:text); 人物ID列表(`character_ids`:json); 场景ID列表(`scene_ids`:json); 道具ID列表(`prop_ids`:json); 人物清单(`characters`:json); 场景清单(`scenes`:json); 道具清单(`props`:json) |
| 道具资产创作 | `agi_prop` | AI 漫剧·道具资产创作：从剧本提取/生成推动剧情的关键道具，生成白底单品图，写入道具资产表并登记 prop_image 资产 | process | 创作项目ID(`creation_id`:any); 补充描述(`text`:text) | 创作项目ID(`creation_id`:text); 道具ID列表(`prop_ids`:json); 道具清单(`props`:json); 道具图(`images`:any) |

### 漫剧·分镜链（`agi_shot`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| 分镜视频制作 | `agi_shot_video` | AI 漫剧·分镜视频制作：以首/尾帧 + 画面描述(场景+运镜)做图生视频（可整章批处理），登记为 shot_video 资产 | process | 分镜ID(单个)(`shot_id`:any); 章节ID(批处理)(`chapter_id`:any); 多章节ID列表(可选)(`chapter_ids`:json); 首帧(`first_frame`:image); 尾帧(`last_frame`:image); 视频提示词(可选)(`text`:text) | 分镜ID(`shot_id`:text); 分镜视频(`video`:video); 分镜ID列表(`shot_ids`:json); 视频列表(`videos`:json) |
| 分镜配音 | `agi_shot_dub` | AI 漫剧·分镜配音：按分镜对话逐句 TTS（依人物 voice_ref 音色克隆，可整章批处理），拼接配音并同步产出 SRT 字幕 | process | 分镜ID(单个)(`shot_id`:any); 章节ID(批处理)(`chapter_id`:any); 多章节ID列表(可选)(`chapter_ids`:json); 分镜视频(可选)(`video`:video); 背景音乐(可选)(`bgm`:audio) | 分镜ID(`shot_id`:text); 配音片段(`audio`:audio); 配音信息(`voiceover`:json); 分镜ID列表(`shot_ids`:json); 配音列表(`audios`:json); SRT字幕列表(`subtitles`:json) |
| 分镜首尾帧 | `agi_shot_frames` | AI 漫剧·分镜首尾帧：为分镜生成首/尾帧概念图（可整章批处理），注入角色多视角图/场景图作为参考图保证一致性 | process | 分镜ID(单个)(`shot_id`:any); 章节ID(批处理)(`chapter_id`:any); 多章节ID列表(可选)(`chapter_ids`:json); 首帧(可选)(`first_frame`:image); 尾帧(可选)(`last_frame`:image) | 分镜ID(`shot_id`:text); 首帧(`first_frame`:image); 尾帧(`last_frame`:image); 分镜ID列表(`shot_ids`:json); 首帧列表(`first_frames`:json); 尾帧列表(`last_frames`:json); 帧图(`images`:any) |
| 组装分镜提示词 | `agi_shot_prompt` | AI 漫剧·组装分镜提示词：把分镜用到的角色图/场景图/道具图按【image1】/【image2】顺序组装，细化为 8 个故事走向关键帧的生图提示词(JSON)，并产出有序参考图供「分镜首尾帧」图生图使用 | process | 分镜ID(单个)(`shot_id`:any); 章节ID(批处理)(`chapter_id`:any); 多章节ID列表(可选)(`chapter_ids`:json) | 分镜ID(`shot_id`:text); 分镜ID列表(`shot_ids`:json); 组装提示词(`image_prompts`:json); 有序参考图(`image_prompt_refs`:json) |

### 漫剧·成片链（`agi_render`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| 分镜导出 | `agi_shot_export` | AI 漫剧·分镜导出：分镜视频+配音+BGM/音效混流成片，可烧录 SRT 字幕（可整章批处理），登记 shot_render 资产 | process | 分镜ID(单个)(`shot_id`:any); 章节ID(批处理)(`chapter_id`:any); 多章节ID列表(可选)(`chapter_ids`:json); 分镜视频(`video`:video); 配音(`audio`:audio); 背景音乐(`bgm`:audio); 音效(`sfx`:audio); SRT字幕(可选)(`subtitle`:any) | 分镜ID(`shot_id`:text); 分镜成片(`render`:video); 分镜ID列表(`shot_ids`:json); 成片列表(`renders`:json) |
| 章节导出 | `agi_chapter_export` | AI 漫剧·章节导出：拼接本章全部分镜成片为一个章节视频，登记 chapter_render 资产 | process | 章节ID(`chapter_id`:any); 多章节ID列表(多章批量)(`chapter_ids`:json); 分镜成片列表(可选)(`renders`:any); 单视频(可选)(`video`:video) | 章节ID(`chapter_id`:text); 章节成片(`render`:video); 章节ID列表(批处理)(`chapter_ids`:json); 章节成片列表(批处理)(`renders`:json) |

### 漫剧·数据链（`agi_data`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| 素材登记入库 | `agi_asset_register` | AI 漫剧·素材登记入库(写素材)：把外部生图/生视频/配音等产物登记为项目资产，并按分镜/章节归属入库，供分镜导出与章节导出节点按分镜消费 | thread | 创作项目ID(`creation_id`:text); 素材文件(`files`:any); 分镜ID(可选)(`shot_id`:text); 章节ID(可选)(`chapter_id`:any) | 创作项目ID(`creation_id`:text); 登记数量(`count`:number); 素材ID列表(`asset_ids`:json); 素材记录(`assets`:json); 素材路径(`paths`:json) |
| 项目数据写入 | `agi_write` | AI 漫剧·项目数据写入(只写)：把外部处理结果回写到项目指定数据点。同一份补丁可批量应用到多个记录ID，也可用带 id 的数组逐条写回；字段需在该类记录的白名单内 | thread | 创作项目ID(`creation_id`:text); 记录ID列表(`ids`:json); 写入数据(JSON)(`data`:json) | 创作项目ID(`creation_id`:text); 数据目标(`target`:text); 写入条数(`count`:number); 记录ID列表(`ids`:json); 写入结果(`updated`:json) |
| 项目数据查询 | `agi_query` | AI 漫剧·项目数据查询(只读)：按目标读取项目/章节/分镜/人物/场景/道具/素材，输出 JSON 与文本。用于把项目内的提示词、台词、设定取出来交给外部节点(LLM/生图/生视频/配音)加工，不修改任何数据 | thread | 创作项目ID(`creation_id`:text); 章节ID(可选)(`chapter_id`:any); 记录ID(可选)(`ids`:json) | 创作项目ID(`creation_id`:text); 数据目标(`target`:text); 记录数(`count`:number); 记录ID列表(`ids`:json); 数据(JSON)(`items`:json); 数据(文本)(`text`:text) |

### AIGC流程链（`aigc`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| ComfyUI 生图 | `aigc_comfyui` | 调用本地/局域网 ComfyUI 实例运行工作流，支持文生图/图生图，参数来自「其他能力接口」设置 | thread | 提示词(`text`:text); 参考视频(`reference_video`:video); 首帧(`first_frame`:image); 图片2(`image2`:image); 图片3(`image3`:image); 图片4(`image4`:image); 尾帧(`last_frame`:image) | 产物列表(`images`:any); 第一个产物(`first`:any); 全部产物(`files`:any) |
| RunningHub 生成 | `aigc_runninghub` | 调用 RunningHub OpenAPI 运行工作流或 AI 应用，生成图片/视频，参数来自「其他能力接口」设置 | process | 提示词(`text`:text); 参考视频(`reference_video`:video); 首帧(`first_frame`:image); 图片2(`image2`:image); 图片3(`image3`:image); 图片4(`image4`:image); 尾帧(`last_frame`:image) | 产物列表(`images`:any); 第一个产物(`first`:any); 全部产物(`files`:any) |
| 即梦 CLI 生成 | `aigc_jimeng` | 通过本地即梦(dreamina) CLI 生成图片或视频，支持文生图/图生图/文生视频/图生视频/首尾帧视频 | process | 提示词(`text`:text); 参考视频(`reference_video`:video); 首帧(`first_frame`:image); 图片2(`image2`:image); 图片3(`image3`:image); 图片4(`image4`:image); 尾帧(`last_frame`:image) | 产物列表(`images`:any); 第一个产物(`first`:any); 全部产物(`files`:any) |
| 图片宫格切割 | `image_grid_split` | 把宫格组合图按 N×N 切成单张图片：支持 4/9/16/25 宫格，可设置外框收缩与内部切缝收缩像素，输出切割后的图片路径列表 | thread | 图片(`image`*:image) | 图片列表(`images`:list) |

### 智能体（`agent`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| OpenCode 智能体 | `opencode_agent` | 把本地 opencode CLI 以工作流节点方式嵌入工作流：注入任务背景与输入输出契约，非交互执行一次 opencode 会话（run --format json），解析事件流并收拢产物到任务 cache 目录。需本机已安装 opencode（或在节点设置中填写可执行文件路径） | process | 输入1(`input_1`:any); 输入2(`input_2`:any) | 输出1(`output_1`:any); 输出2(`output_2`:any) |
| 剪辑AI Agent | `editor_agent` | 接收上游剪辑项目JSON，按编辑指令对时间线二次精选，输出精选后的剪辑json | process | 剪辑项目(`project`:json); 编辑指令(`text`:text) | 剪辑项目(`project`:json); 运行记录(`artifacts`:json); 执行结果(`result`:text) |
| 小pi通用智能体 | `pi_agent` | 将小 Pi 以工作流节点方式嵌入工作流：注入任务背景与输入输出契约，发起一次 Pi 会话并执行任务，产物保存到任务 cache 目录 | process | 输入1(`input_1`:any); 输入2(`input_2`:any) | 输出1(`output_1`:any); 输出2(`output_2`:any) |

### 流程控制节点（`flow_control`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| 写入任务信息 | `set_task_info` | 「获取任务信息」的逆向：用上游输入值写回任务元信息（任务名称、输入语言、输出语言、变量1、变量2），供下游节点与「获取任务信息」读取；节点本身不产出文件 | thread | 任务名称(`task_name`:text); 输入语言(`input_language`:text); 输出语言(`output_language`:text); 变量1(`var1`:text); 变量2(`var2`:text) | 执行完成情况(`result`:any) |
| 定时执行 | `timed_delay` | 等待指定时间后继续执行，支持时间点和倒计时两种模式 | thread | 输入(`any`:any) | 输出(`any`:any) |
| 工作流执行器 | `workflow_runner` | 容器化执行一个已存在的工作流：把子工作流的输入映射为本节点输入，把拓扑终点节点的输出作为本节点输出。默认在当前任务目录下新建独立子目录执行，避免与父流程文件互相污染 | thread | 输入1(`in_1`:any); 输入2(`in_2`:any); 输入3(`in_3`:any); 输入4(`in_4`:any) | 输出1(`out_1`:any); 输出2(`out_2`:any); 输出3(`out_3`:any); 输出4(`out_4`:any); 输出汇总(`result`:json); 产物列表(`artifacts`:json) |
| 循环 | `loop` | 接收一个列表作为迭代对象，逐条取出驱动循环体内的子流程执行；每次迭代的产物按序号记录在 manifest 清单中（选中若干已连线节点后创建循环体） | thread | 迭代对象(`items`:json) | 产物清单(`results`:json); 迭代总数(`count`:json) |
| 获取任务信息 | `get_task_info` | 从 task.json 与输入节点配置读取任务元信息并作为文本输出：任务名称、输入语音、输出语言、变量1、变量2，供下游节点使用 | thread | 输入(`any`:any) | 任务名称(`task_name`:text); 输入语言(`input_language`:text); 输出语言(`output_language`:text); 变量1(`var1`:text); 变量2(`var2`:text) |
| 运行等待 | `run_wait` | 开启后等待指定时长，超时可选择抛出错误或标记完成继续；关闭则跳过并透传输入。进入等待时会发送系统通知提醒用户。 | thread | 输入(`input`:any) | 输出(`output`:any) |

### 网络请求类节点（`network_request`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| QM虚拟邮箱 | `qm_virtual_mailbox` | 通过晴沐智坊虚拟邮箱，向已验证的转发目标发送验证码邮件。费用2分钱/条（云端处理）。使用前请确保已在网页端设置并验证转发目标。详情访问：https://www.licorxj.online/mail-forwarding | thread | 文本内容(`text`:text) | 发送结果(`json`:json) |
| 图床网存-kie | `kie_media_host` | 把本地图片 / 视频 / 音频上传到 KIE 免费媒体暂存，返回可直接访问的外链 URL，供其它接口（生图、生视频、对口型、图声生视频等）引用。支持 image / video / audio / file 四个输入口，可同时上传多个文件（已连接的口都会上传）。注意：本节点仅做文件暂存，不消耗生成额度；使用前请先注册 KIE 账号并获取 API Key，填入【全局设置 → 密钥管理器】，密钥名称必须为 KIEAI_API_KEY（也可在系统环境变量中设置同名变量）。 | process | 图片(`image`:image); 视频(`video`:video); 音频(`audio`:audio); 其它文件(`file`:filepath) | 首个链接(`url`:url); 链接列表(`urls`:json); 上传明细(`json`:json) |
| 媒体转链接 | `media_to_url` | 上传本地视频/图片到腾讯云 VOD，返回 URL 及完整媒体详情（尺寸/时长/码率等）保存为 JSON | thread | 视频(`video`:video); 图片(`image`:image) | 媒体详情(`json`:json) |
| 平台视频下载 | `platform_download` | 使用 yt-dlp 下载平台视频 | process | URL(`url`*:url) | 视频(`video`:video); 字幕(`subtitle`:subtitle); 封面(`image`:image); 下载文件名(`filename`:text) |
| 批量视频下载 | `batch_download` | 使用 yt-dlp 的专辑/播放列表批量下载能力，一次下载整张专辑；产物统一保存到新建的专辑目录，并输出下载产物清单 JSON | process | 专辑/播放列表 URL(`url`*:url) | 下载产物清单(`json`:json); 产物目录(`folder`:text); 首个视频(`video`:video) |
| 文件下载器 | `file_downloader` | 按「下载地址」下载文件到任务目录的 download/ 文件夹；「文件名称」留空时自动命名（Content-Disposition → URL 末段 → 时间戳），缺扩展名按响应类型补全。输出下载后的文件路径 | process | 下载地址(`url`*:url); 文件名称(`filename`:text) | 文件路径(`file`:filepath); 文件名(`filename`:text) |
| 网络请求 | `http_request` | 执行可配置的 HTTP 网络请求，支持请求体占位符、重试和响应保存 | process | 输入 1(`input_1`:any); 输入 2(`input_2`:any); 输入 3(`input_3`:any); 请求 Data(`request_data`:json) | 结果文件(`result`:any); JSON 结果(`json`:json); 文本结果(`text`:text); 状态码(`status`:text) |

### 工具类节点（`utility`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| JSON取值 | `json_get` | 按key表达式从输入JSON中取值，输出端口数量可在卡片上用+号任意增加（1~8），每个端口下对应一个取值表达式；结果以any类型输出，数据不落盘（内存流转给下游，并写入任务数据库） | thread | JSON(`json`:json) | 取值1(`out_1`:any) |
| JSON可视化编辑 | `json_visual_editor` | 可视化编辑 JSON，默认透传，可另存副本 | thread | JSON(`json`*:json) | JSON(`json`:json) |
| JSON编辑 | `json_editor` | 按key表达式修改JSON中指定字段的值，覆盖保存原文件 | thread | JSON(`json`:json); 修改值(`text`:text) | JSON(`json`:json) |
| JSON转文本 | `json_to_text` | 将JSON转换为文本文件，支持全量转文本或按key表达式取值 | thread | JSON(`json`:json) | 文本文件(`text`:text) |
| SRT字幕转json | `srt_to_json` | 将 SRT 字幕转换为 ASR 结果格式 JSON（包含 text 与 segments，不生成词级时间戳 words），可直接接入 ASR 结果校验、预处理等下游节点。输入为「字幕」类型，可连线「字幕生成」等字幕节点的输出（默认输出 .srt）。 | thread | 字幕(`subtitle`*:subtitle) | ASR结果JSON(`json`:json) |
| SRT转文本 | `srt_to_text` | 将 SRT 字幕直接转换为纯文本：去掉序号与时间轴，提取每条字幕的文本内容，按原顺序拼接为 .txt 文本文件输出。输入为「字幕」类型，可连线「字幕生成」等字幕节点的输出（默认输出 .srt）。 | thread | 字幕(`subtitle`*:subtitle) | 文本(`text`:text) |
| 字幕编辑 | `subtitle_editor` | 逐条编辑字幕（文本/时间/合并/拆分），带视频预览，默认透传，可另存副本 | thread | 字幕(`subtitle`*:subtitle) | 字幕(`subtitle`:subtitle) |
| 文本拼接 | `text_concat` | 把「输入1 / 输入2 / 输入框文本」三个对象按卡片指定顺序拼接，连接符可选换行符/空格/自定义 | thread | 输入1(`input1`:text); 输入2(`input2`:text) | 拼接文本(`text`:text) |
| 文本编辑 | `text_editor` | 可视化编辑文本，支持查找删除/替换/正则，默认透传，可另存副本 | thread | 文本(`text`*:text) | 文本(`text`:text) |
| 视频发布 | `video_publish` | 将视频发布到指定社交平台，支持多平台分发、定时发布、草稿模式 | process | 视频(`video`*:video); 横屏封面(`cover_landscape`:image); 竖屏封面(`cover_portrait`:image); 标题/描述(`json`:json) | 发布结果(`text`:text); 结果文件(`result_file`:file) |
| 输出合并为列表 | `output_merge_list` | 将多个上游节点的输出（文本或路径）合并为列表格式 JSON，内存传递、不落盘；输入端口数量可在卡片上动态加减 | thread | — | 列表JSON(`json`:json) |

### 文件操作类节点（`file`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| 取文件路径 | `resolve_path` | 以相对路径拼接出项目文件夹内的特定文件路径 | thread | 输入(`input`:any) | 路径(`output`:any) |
| 文件改名 | `file_rename` | 给输入文件改名，支持自定义文件名、前缀、后缀，或从输入端口动态获取文件名；重名时自动追加序号 | thread | 输入(`any`*:any); 文件名(来自输入)(`name`:text) | 输出(`any`:any) |
| 路径转标题 | `path_to_title` | 从文件路径提取组件并拼装标题 | thread | 输入(`any`:any) | 标题(`text`:text) |

### 组合节点（`group_node`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| 组合 | `groupnode_mu37rfk8` | 组合（组合节点） | — | 音频分离 / 视频(`gin_1`:video) | — |
| 组合 | `groupnode_mu37s0wv` | 组合（组合节点） | — | 音频分离 / 视频(`gin_1`:video) | — |
| 语音识别 | `groupnode_mty81wvt` | 语音识别（组合节点） | — | ASR后处理 / 对齐音源(`gin_1`:audio); ASR后处理 / 人声音源(`gin_2`:audio); 语音识别 (ASR) / ASR音源(`gin_3`:audio) | — |

### asset（`asset`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| 图片素材库 | `image_asset_library` | 从公共图片素材库选择素材（记录素材ID），执行时回查详情并复制到当前工作文件夹；输出素材路径与素材全信息 JSON。 | process | 来源(`any`:any) | 素材路径(`image`:image); 素材全信息JSON(`info`:json) |
| 新建音色角色 | `voice_character` | LLM 根据角色描述/面板设计生成朗读提示词与TTS指令，合成角色默认音色片段与多情绪片段，并写入配音谷音色库；输出音色ID、主片段音频与全信息JSON。 | process | 角色描述文本(`description`:any); 角色设计JSON(`design_json`:json) | 音色ID(`voice_id`:text); 音色主片段音频(`audio`:audio); 音色全信息JSON(`info`:json) |
| 素材入库 | `material_storage` | 将接入的视频/图片/音频素材归档到项目公共素材库并写入数据库。后端自动识别素材类型，按前端设置的素材属性（名称/分组标签/自定义标签/描述）入库，支持视频、图片、音频三种类型。 | thread | 素材(`media`:any) | 素材路径(`material`:any); 素材库引用(`library_ref`:text); 素材类型(`asset_type`:text); 素材ID(`asset_id`:text) |
| 视频素材库 | `video_asset_library` | 从公共视频素材库选择素材（记录素材ID），执行时回查详情并复制到当前工作文件夹；输出素材路径与素材全信息 JSON。 | process | 来源(`any`:any) | 素材路径(`video`:video); 素材全信息JSON(`info`:json) |
| 角色素材库 | `character_asset_library` | 从公共角色库选择角色（记录角色ID），执行时回查角色详情并把多视角图文件夹复制到工作目录；输出素材路径（图片文件夹）与角色全信息 JSON。 | process | 来源(`any`:any) | 素材路径(图片文件夹)(`path`:filepath); 素材全信息JSON(`info`:json) |
| 音色素材库 | `voice_asset_library` | 从晴沐配音谷音色库选择音色（记录音色ID），执行时回查音色详情并把设计样音复制到工作目录；输出素材路径（试听音频）与音色全信息 JSON。 | process | 来源(`any`:any) | 素材路径(试听音频)(`audio`:audio); 素材全信息JSON(`info`:json) |
| 音频素材库 | `audio_asset_library` | 从 URL、本地路径或晴沐配音谷素材库（ID）获取音频素材，下载/复制到当前工作文件夹；输出素材路径与素材全信息 JSON。 | process | 来源(`any`:any) | 素材路径(`audio`:audio); 素材全信息JSON(`info`:json) |

### cutia（`cutia`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| 剪辑渲染 | `cutia_render` | 接收上游精选后的剪辑项目JSON，无头加载并渲染导出成片，无需人工打开剪辑工作台 | thread | 剪辑项目(`project`:json) | 渲染成片(`video`:video) |
| 剪辑项目初始化 | `project_init` | 收集上游素材并构造初始剪辑JSON（默认时间线骨架+素材清单），供「Cutia 交互剪辑」接力整理筛选 | thread | 视频(`video`:video); 音频(`audio`:audio); 图片(`image`:image); 字幕(`subtitle`:subtitle) | 初始剪辑项目(`project`:json) |
| 推送到剪辑台 | `cutia` | 将剪辑项目JSON推送到剪辑工作台并发起系统提醒，等待剪辑后透传输出（素材编排由上游「剪辑项目初始化」完成） | thread | 剪辑项目(`project`:json) | 剪辑项目(`project`:json) |
| 添加剪辑素材到轨道 | `add_track_media` | 接收任意类型素材，按所选类型添加到剪辑项目轨道（可新建轨道/轨道尾部/自定义插入点），输出剪辑项目JSON | thread | 剪辑项目(`project`:json); 素材(`media`:any) | 剪辑项目(`project`:json) |

### hyperframes（`hyperframes`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| HyperFrames 创意 | `hyperframes_creative` | 两步走第一步：把 URL / 主题 / PR / 素材收敛成一份 BRIEF.md 创意简报；支持加载已有 BRIEF.md 稳定复用既有工作流，不重复做意图访谈 | process | 素材/主题(`source`:any); 附加素材(`assets`:any); 已有 BRIEF.md(`brief`:filepath) | BRIEF.md(`brief`:filepath); 项目目录(`project_dir`:filepath); 创意摘要(`summary`:text) |
| HyperFrames 单文件渲染 | `hyperframe_render` | 【自定义】直接把一段 HTML 合成脚本交给 HyperFrames CLI 渲染成片，不经过 BRIEF.md 与工作流路由；成片由工作流驱动时使用「HyperFrames 渲染」节点 | — | HTML 内容(`html_content`*:text); HTML 文件路径(`html_file`:filepath) | 渲染视频(`video`:video); 渲染结果(`json`:json); 输出信息(`text`:text) |
| HyperFrames 工具 | `hyperframes_cli` | 附属工具调用节点：直接在工作目录执行一条 HyperFrames CLI 命令，覆盖技能安装/体检、工程初始化、网站抓取、Registry 组件、关键帧诊断、校验、升级、预览、渲染与发布 | process | 项目目录(`project_dir`:filepath); 附加输入(`input`:any) | 执行日志(`output`:filepath); 输出文本(`stdout`:text) |
| HyperFrames 智能体 | `hyperframes_agent` | 复合节点：直接驱动本项目的小 Pi（piagent）框架，一个节点跑完「创意 → 渲染」整条链路；检测到已有 BRIEF.md 时自动按加载模式复用既有工作流 | process | 素材/主题(`source`:any); 附加素材(`assets`:any); 已有 BRIEF.md(`brief`:filepath) | 成片(`video`:video); BRIEF.md(`brief`:filepath); 项目目录(`project_dir`:filepath); 执行摘要(`text`:text) |
| HyperFrames 渲染 | `hyperframes_render` | 两步走第二步：读取 BRIEF.md，按其中的工作流路由构建 HTML 合成并渲染成片；支持只构建 / 只渲染 / 只校验，可勾选渲染后 publish 出分享链接 | process | BRIEF.md(`brief`:filepath); 项目目录(`project_dir`:filepath); 附加素材(`assets`:any) | 成片(`video`:video); 项目目录(`project_dir`:filepath); BRIEF.md(`brief`:filepath); 发布链接(`url`:url) |

### music_gen（`music_gen`）

| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |
|------|----|------|-------|---------|---------|
| AI音乐-上传并扩展 | `music_upload_extend` | 上传本地音频并续写扩展：参考音频从连线 audio 输入，可指定续写起点与提示词。 | process | 本地音频(`audio`:audio); 续写提示词(`text`:text) | 音频(`audio`:audio); 音频列表(`audios`:json); 生成参数JSON(`params`:json) |
| AI音乐-人声分离 | `music_separate` | 对已有曲目做分轨分离（人声 / 伴奏 / 鼓 / 贝斯等）。可接上游音频文件，也可从上游参数 JSON 取 task_id / audio_id。 | process | 提示词 / 歌词(`text`:text); 待分离音频(`audio`:audio); 上游音乐参数JSON(`json`:json) | 音频(`audio`:audio); 音频列表(`audios`:json); 生成参数JSON(`params`:json) |
| AI音乐-文生音乐 | `music_txt2music` | 根据提示词 / 歌词生成完整歌曲（含人声）。提示词可来自连线文本输入或节点内自定义；产物为音频。 | process | 提示词 / 歌词(`text`:text) | 音频(`audio`:audio); 音频列表(`audios`:json); 生成参数JSON(`params`:json) |
| AI音乐-歌词生成 | `music_lyrics` | 根据主题描述生成歌词文本（不产出音频）。主题可来自连线文本输入或节点内自定义；输出歌词文本供「文生音乐」等节点使用。 | process | 提示词 / 歌词(`text`:text) | 歌词文本(`text`:text); 生成参数JSON(`params`:json) |
| AI音乐-添加人声 | `music_add_vocals` | 为伴奏 /  instrumental 轨道添加人声：上传音频并提供歌词或演唱提示词。 | process | 伴奏音频(`audio`:audio); 歌词/演唱提示(`text`:text) | 音频(`audio`:audio); 音频列表(`audios`:json); 生成参数JSON(`params`:json) |
| AI音乐-添加伴奏 | `music_add_instrumental` | 为人声 / 干声轨道添加伴奏：上传音频后生成带伴奏的完整曲目。 | process | 人声音频(`audio`:audio); 标题/标签(`text`:text) | 音频(`audio`:audio); 音频列表(`audios`:json); 生成参数JSON(`params`:json) |
| AI音乐-纯音乐 | `music_instrumental` | 根据风格描述生成无人声的纯音乐 / 伴奏。提示词可来自连线文本输入或节点内自定义。 | process | 提示词 / 歌词(`text`:text) | 音频(`audio`:audio); 音频列表(`audios`:json); 生成参数JSON(`params`:json) |
| AI音乐-翻唱/风格迁移 | `music_cover` | 上传参考音频并按提示词 / 风格做翻唱或风格迁移。参考音频从连线 audio 输入（本地文件自动上传）。 | process | 参考音频(`audio`:audio); 风格/提示词(`text`:text) | 音频(`audio`:audio); 音频列表(`audios`:json); 生成参数JSON(`params`:json) |
| AI音乐-转WAV | `music_to_wav` | 把已有曲目转换为 WAV 无损格式：从上游音乐节点的参数 JSON 取 task_id / audio_id。 | process | 上游音乐参数JSON(`json`:json) | WAV音频(`audio`:audio); 生成参数JSON(`params`:json) |
| AI音乐-音乐扩展 | `music_extend` | 对已有曲目做续写扩展：从上游音乐节点的参数 JSON 取 audio_id（也可直接填 audio_id），可指定续写起点与续写提示词。 | process | 上游音乐参数JSON(`json`:json); 续写提示词(`text`:text) | 音频(`audio`:audio); 音频列表(`audios`:json); 生成参数JSON(`params`:json) |
