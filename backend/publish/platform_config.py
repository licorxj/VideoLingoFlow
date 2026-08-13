"""Platform metadata constants for video publishing service."""

PLATFORMS = {
    1: {"name": "小红书", "key": "xiaohongshu", "color": "#ff2442"},
    2: {"name": "视频号", "key": "shipinhao", "color": "#07c160"},
    3: {"name": "抖音", "key": "douyin", "color": "#000000"},
    4: {"name": "快手", "key": "kuaishou", "color": "#ff4906"},
    5: {"name": "B站", "key": "bilibili", "color": "#00a1d6"},
    6: {"name": "百家号", "key": "baijiahao", "color": "#2932e1"},
    7: {"name": "TikTok", "key": "tiktok", "color": "#000000"},
    8: {"name": "YouTube", "key": "youtube", "color": "#ff0000"},
    9: {"name": "腾讯视频", "key": "tengxun", "color": "#ff6a00"},
    10: {"name": "爱奇艺", "key": "iqiyi", "color": "#00be06"},
}

PLATFORM_NAMES = {v["name"]: k for k, v in PLATFORMS.items()}
PLATFORM_KEYS = {v["key"]: k for k, v in PLATFORMS.items()}
