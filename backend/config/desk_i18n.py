"""AI剪辑链（OpenChatCut occ CLI）工具与参数的中文显示名。

只影响**展示**：``tool_schemas()`` 会把这里的 label / 描述附加到接口返回上，
前端下拉与参数表单显示中文；实际调用仍使用英文工具名与英文参数 key。
新增工具时若未收录，前端自动回退英文原名。
"""
from __future__ import annotations

# 工具中文名 + 一句话说明
TOOL_ZH: dict[str, dict[str, str]] = {
    "read_project": {"label": "读取工程信息", "desc": "查看工程概览、时间线、轨道、片段或素材库"},
    "read_timeline": {"label": "读取时间线", "desc": "读取当前时间线：帧率与全部片段（含素材关联、源窗口、变换、特效）"},
    "read_script": {"label": "读取剪辑脚本", "desc": "把当前时间线导出为 timeline.md（分段 id 编码的 Markdown）"},
    "read_captions": {"label": "读取字幕", "desc": "查看字幕轨的文本、样式与版式"},
    "read_transcript": {"label": "读取转写文本", "desc": "按短语分组读取时间线上的转写内容"},
    "read_agent_artifact": {"label": "读取执行结果", "desc": "分页读取之前工具调用归档的结果"},
    "find_transcript": {"label": "查找台词位置", "desc": "搜索某句话在何时被说出，返回时间轴帧范围"},
    "list_templates": {"label": "列出模板", "desc": "浏览动态图形模板分类与名称（内置约 211 个）"},
    "search_templates": {"label": "搜索模板", "desc": "按名称/分类关键词模糊搜索模板"},
    "list_audio": {"label": "列出音频素材", "desc": "浏览音频库里的音乐/音效素材"},
    "browse_library": {"label": "浏览素材库", "desc": "浏览素材库（特效/文字/音效/贴纸等）"},
    "browse_local_media": {"label": "浏览本地媒体", "desc": "浏览本地目录里的媒体文件"},
    "import_asset": {"label": "导入单个素材", "desc": "把一个本地媒体文件（视频/图片/音频）导入媒体池"},
    "import_assets": {"label": "批量导入素材", "desc": "把多个本地媒体路径一次性导入媒体池"},
    "import_folder": {"label": "导入整个目录", "desc": "递归导入本地目录内所有受支持的媒体文件"},
    "import_timeline": {"label": "导入时间线", "desc": "从 FCPXML / EDL 文件导入一条可编辑的时间线"},
    "add_audio": {"label": "添加音频到轨道", "desc": "把音频库素材作为片段放到音频轨（A1/A2）"},
    "add_motion_graphic": {"label": "添加模板到轨道", "desc": "把动态图形模板作为片段放到视频轨（标题、字幕条、贴纸等）"},
    "edit_item": {"label": "片段增删改", "desc": "统一的片段级操作：添加视频/图片/音频/文字/纯色/特效/转场，或更新、删除片段"},
    "edit_track": {"label": "轨道管理", "desc": "轨道的增删改、重命名、重排与整理"},
    "edit_captions": {"label": "字幕设置", "desc": "开关字幕、应用样式模板、改文本、选来源轨与避让人脸"},
    "update_item_props": {"label": "修改片段属性", "desc": "改片段的可编辑属性（文本内容、颜色等）"},
    "move_item": {"label": "移动片段", "desc": "把片段移到别的轨道或改起始位置"},
    "set_item_timing": {"label": "设置片段时序", "desc": "改片段的起始帧/时长，设置淡入淡出，可联动后移"},
    "split_item": {"label": "切割片段", "desc": "在指定帧把片段一分为二"},
    "duplicate_item": {"label": "复制片段", "desc": "复制片段并追加到轨道末尾"},
    "remove_item": {"label": "删除片段", "desc": "删除片段，可闭合留下的空隙"},
    "clear_timeline": {"label": "清空时间线", "desc": "删除全部片段（仅在明确要求重来时才用）"},
    "set_aspect_ratio": {"label": "设置画布比例", "desc": "改画布宽高比（contain 加黑边 / cover 裁剪填充）"},
    "manage_effects": {"label": "片段特效", "desc": "给片段添加/更新/移除 WebGL 特效与 LUT"},
    "manage_markers": {"label": "标记管理", "desc": "在时间线上添加批注/TODO 标记（点或区间）"},
    "manage_timelines": {"label": "多时间线管理", "desc": "时间线（序列）的新建/复制/切换/改名/删除，或作为嵌套序列插入"},
    "update_watermark": {"label": "水印设置", "desc": "设置文字水印的开关、文本、位置与不透明度"},
    "apply_script": {"label": "提交剪辑脚本", "desc": "把编辑后的 timeline.md 原子提交回时间线（任一行非法则整体拒绝）"},
    "export_jianying_draft": {"label": "导出剪映草稿", "desc": "导出为剪映/CapCut 草稿，交给剪映继续精修"},
}

# 参数中文名：按工具分组（同名参数在不同工具下含义可能不同）
PARAM_ZH: dict[str, dict[str, str]] = {
    "read_project": {
        "view": "查看范围", "timelineId": "时间线ID", "track": "轨道",
        "fromFrame": "起始帧", "toFrame": "结束帧", "itemId": "片段ID",
        "assetId": "素材ID", "code": "含模板代码", "projectId": "工程ID（忽略）",
    },
    "read_timeline": {"track": "轨道", "timelineId": "时间线ID"},
    "read_script": {"track": "轨道", "showSilence": "包含静音段"},
    "read_captions": {"captionTrackId": "字幕轨", "track": "来源轨"},
    "read_transcript": {
        "itemId": "片段ID", "track": "轨道", "silenceThresholdSeconds": "静音阈值(秒)",
        "maxWordsPerPhrase": "每短语最多词数", "offset": "偏移", "limit": "数量上限",
    },
    "read_agent_artifact": {"artifactId": "结果ID", "pointer": "字段路径", "offset": "偏移", "limit": "数量上限"},
    "find_transcript": {
        "query": "搜索内容", "asset": "素材", "track": "轨道", "fuzzy": "模糊匹配",
        "includeWordTimestamps": "含词级时间戳", "limit": "数量上限",
    },
    "list_templates": {"category": "分类"},
    "search_templates": {"query": "搜索关键词"},
    "list_audio": {"query": "搜索关键词", "category": "分类", "limit": "数量上限"},
    "browse_library": {
        "category": "分类", "group": "分组", "query": "搜索关键词", "id": "素材ID",
        "limit": "数量上限", "offset": "偏移",
    },
    "browse_local_media": {"path": "本地目录", "query": "搜索关键词", "kind": "类型", "recursive": "递归子目录", "offset": "偏移", "limit": "数量上限"},
    "import_asset": {"path": "素材文件路径"},
    "import_assets": {"paths": "素材文件路径列表"},
    "import_folder": {"path": "目录路径"},
    "import_timeline": {
        "format": "格式", "content": "文件内容", "name": "时间线名称", "activate": "导入后打开",
        "fps": "帧率", "startTimecode": "起始时间码",
    },
    "add_audio": {"audioName": "音频素材名", "track": "轨道", "startFrame": "起始帧", "ripple": "插入模式（后移片段）"},
    "add_motion_graphic": {"templateName": "模板名称", "track": "轨道", "startFrame": "起始帧", "ripple": "插入模式（后移片段）"},
    "edit_item": {
        "adds": "新增（数组）", "updates": "修改（数组）", "deletes": "删除（数组）",
        "ripple": "插入模式（后移片段）", "validateOnly": "仅校验不执行", "projectId": "工程ID（忽略）",
    },
    "edit_track": {"action": "操作", "json": "参数JSON", "trackId": "轨道ID", "trackIds": "轨道ID列表"},
    "edit_captions": {
        "action": "操作", "json": "参数JSON", "templatePreset": "样式模板", "preset": "预设",
        "motionPreset": "动画预设", "trackId": "来源轨", "trackOrder": "轨道序号",
        "list": "仅列出可选轨", "captionTrackId": "字幕轨", "captionsItemId": "字幕轨（旧名）",
    },
    "update_item_props": {"itemId": "片段ID", "props": "属性（JSON）"},
    "move_item": {"itemId": "片段ID", "track": "目标轨道", "startFrame": "起始帧"},
    "set_item_timing": {
        "itemId": "片段ID", "startFrame": "起始帧", "durationInFrames": "时长(帧)",
        "fadeInSeconds": "淡入(秒)", "fadeOutSeconds": "淡出(秒)", "ripple": "联动后移",
    },
    "split_item": {"itemId": "片段ID", "atFrame": "切割位置(帧)"},
    "duplicate_item": {"itemId": "片段ID"},
    "remove_item": {"itemId": "片段ID", "ripple": "闭合空隙"},
    "clear_timeline": {},
    "set_aspect_ratio": {"ratio": "宽高比", "fit": "适配方式"},
    "manage_effects": {
        "action": "操作", "targetItemId": "目标片段ID", "effectId": "特效实例ID",
        "assetId": "特效ID", "propertyOverrides": "参数覆盖(JSON)",
    },
    "manage_markers": {
        "action": "操作", "timelineId": "时间线ID", "fromFrame": "所在帧", "durationFrames": "时长(帧)",
        "note": "备注文本", "color": "颜色", "scope": "作用范围", "itemId": "片段ID",
        "markerId": "标记ID", "transcriptSegments": "转写分段", "transcriptTrack": "转写轨",
        "notePrefix": "备注前缀", "markers": "批量创建", "updates": "批量修改",
    },
    "manage_timelines": {
        "action": "操作", "timelineId": "时间线ID", "timelineIds": "时间线ID列表",
        "name": "名称", "ratio": "宽高比", "width": "宽(px)", "height": "高(px)",
        "fit": "适配方式", "hidden": "隐藏", "activate": "创建后激活",
        "timelines": "批量创建", "track": "目标轨", "startFrame": "起始帧",
        "sourceStartFrame": "源起始帧", "sourceDurationInFrames": "源时长(帧)", "playbackRate": "播放速度",
    },
    "update_watermark": {"enabled": "启用", "text": "水印文本", "position": "位置", "opacity": "不透明度", "size": "字号"},
    "apply_script": {"timelineMd": "timeline.md 内容", "preview": "仅预校验", "track": "轨道"},
    "export_jianying_draft": {"draftName": "草稿名称", "draftsDir": "输出目录"},
}
