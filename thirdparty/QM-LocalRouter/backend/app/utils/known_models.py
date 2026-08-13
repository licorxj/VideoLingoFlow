KNOWN_MODELS = {
    # OpenAI models
    "gpt-4o": {"display_name": "GPT-4o", "is_multimodal": True, "model_type": "text", "context_window": 128000, "temperature": 1.0, "price_input": 2.5, "price_output": 10.0},
    "gpt-4o-2024-05-13": {"display_name": "GPT-4o (2024-05-13)", "is_multimodal": True, "model_type": "text", "context_window": 128000, "temperature": 1.0, "price_input": 5.0, "price_output": 15.0},
    "gpt-4o-2024-08-06": {"display_name": "GPT-4o (2024-08-06)", "is_multimodal": True, "model_type": "text", "context_window": 128000, "temperature": 1.0, "price_input": 2.5, "price_output": 10.0},
    "gpt-4o-mini": {"display_name": "GPT-4o Mini", "is_multimodal": True, "model_type": "text", "context_window": 128000, "temperature": 1.0, "price_input": 0.15, "price_output": 0.6},
    "gpt-4o-mini-2024-07-18": {"display_name": "GPT-4o Mini (2024-07-18)", "is_multimodal": True, "model_type": "text", "context_window": 128000, "temperature": 1.0, "price_input": 0.15, "price_output": 0.6},
    "gpt-4-turbo": {"display_name": "GPT-4 Turbo", "is_multimodal": True, "model_type": "text", "context_window": 128000, "temperature": 1.0, "price_input": 10.0, "price_output": 30.0},
    "gpt-4-turbo-2024-04-09": {"display_name": "GPT-4 Turbo (2024-04-09)", "is_multimodal": True, "model_type": "text", "context_window": 128000, "temperature": 1.0, "price_input": 10.0, "price_output": 30.0},
    "gpt-4": {"display_name": "GPT-4", "is_multimodal": False, "model_type": "text", "context_window": 8192, "temperature": 1.0, "price_input": 30.0, "price_output": 60.0},
    "gpt-3.5-turbo": {"display_name": "GPT-3.5 Turbo", "is_multimodal": False, "model_type": "text", "context_window": 16385, "temperature": 1.0, "price_input": 0.5, "price_output": 1.5},
    "gpt-3.5-turbo-0125": {"display_name": "GPT-3.5 Turbo (0125)", "is_multimodal": False, "model_type": "text", "context_window": 16385, "temperature": 1.0, "price_input": 0.5, "price_output": 1.5},
    "o1": {"display_name": "o1", "is_multimodal": True, "model_type": "text", "context_window": 200000, "temperature": 1.0, "price_input": 15.0, "price_output": 60.0},
    "o1-mini": {"display_name": "o1 Mini", "is_multimodal": False, "model_type": "text", "context_window": 128000, "temperature": 1.0, "price_input": 3.0, "price_output": 12.0},
    "o1-preview": {"display_name": "o1 Preview", "is_multimodal": False, "model_type": "text", "context_window": 128000, "temperature": 1.0, "price_input": 15.0, "price_output": 60.0},
    "o3-mini": {"display_name": "o3 Mini", "is_multimodal": False, "model_type": "text", "context_window": 200000, "temperature": 1.0, "price_input": 1.1, "price_output": 4.4},
    "gpt-4-1": {"display_name": "GPT-4.1", "is_multimodal": True, "model_type": "text", "context_window": 1047576, "temperature": 1.0, "price_input": 2.0, "price_output": 8.0},
    "gpt-4.1-mini": {"display_name": "GPT-4.1 Mini", "is_multimodal": True, "model_type": "text", "context_window": 1047576, "temperature": 1.0, "price_input": 0.4, "price_output": 1.6},
    "gpt-4.1-nano": {"display_name": "GPT-4.1 Nano", "is_multimodal": True, "model_type": "text", "context_window": 1047576, "temperature": 1.0, "price_input": 0.1, "price_output": 0.4},
    "o3": {"display_name": "o3", "is_multimodal": True, "model_type": "text", "context_window": 200000, "temperature": 1.0, "price_input": 10.0, "price_output": 40.0},
    "o4-mini": {"display_name": "o4 Mini", "is_multimodal": True, "model_type": "text", "context_window": 200000, "temperature": 1.0, "price_input": 1.1, "price_output": 4.4},
    # Embedding models
    "text-embedding-3-small": {"display_name": "Embedding 3 Small", "is_multimodal": False, "model_type": "embedding", "context_window": 8191, "temperature": None, "price_input": 0.02, "price_output": 0.0},
    "text-embedding-3-large": {"display_name": "Embedding 3 Large", "is_multimodal": False, "model_type": "embedding", "context_window": 8191, "temperature": None, "price_input": 0.13, "price_output": 0.0},
    "text-embedding-ada-002": {"display_name": "Embedding Ada 002", "is_multimodal": False, "model_type": "embedding", "context_window": 8191, "temperature": None, "price_input": 0.1, "price_output": 0.0},
    # Image models
    "dall-e-3": {"display_name": "DALL-E 3", "is_multimodal": False, "model_type": "image", "context_window": None, "temperature": None, "price_input": 0.0, "price_output": 0.0},
    "dall-e-2": {"display_name": "DALL-E 2", "is_multimodal": False, "model_type": "image", "context_window": None, "temperature": None, "price_input": 0.0, "price_output": 0.0},
    "gpt-image-1": {"display_name": "GPT Image 1", "is_multimodal": True, "model_type": "image", "context_window": None, "temperature": None, "price_input": 0.0, "price_output": 0.0},
    # TTS models
    "tts-1": {"display_name": "TTS 1", "is_multimodal": False, "model_type": "tts", "context_window": None, "temperature": None, "price_input": 0.0, "price_output": 0.0},
    "tts-1-hd": {"display_name": "TTS 1 HD", "is_multimodal": False, "model_type": "tts", "context_window": None, "temperature": None, "price_input": 0.0, "price_output": 0.0},

    # Claude models (Anthropic)
    "claude-sonnet-4-20250514": {"display_name": "Claude Sonnet 4", "is_multimodal": True, "model_type": "text", "context_window": 200000, "temperature": 1.0, "price_input": 3.0, "price_output": 15.0},
    "claude-3-5-sonnet-20241022": {"display_name": "Claude 3.5 Sonnet", "is_multimodal": True, "model_type": "text", "context_window": 200000, "temperature": 1.0, "price_input": 3.0, "price_output": 15.0},
    "claude-3-5-haiku-20241022": {"display_name": "Claude 3.5 Haiku", "is_multimodal": True, "model_type": "text", "context_window": 200000, "temperature": 1.0, "price_input": 0.8, "price_output": 4.0},
    "claude-3-opus-20240229": {"display_name": "Claude 3 Opus", "is_multimodal": True, "model_type": "text", "context_window": 200000, "temperature": 1.0, "price_input": 15.0, "price_output": 75.0},
    "claude-3-sonnet-20240229": {"display_name": "Claude 3 Sonnet", "is_multimodal": True, "model_type": "text", "context_window": 200000, "temperature": 1.0, "price_input": 3.0, "price_output": 15.0},
    "claude-3-haiku-20240307": {"display_name": "Claude 3 Haiku", "is_multimodal": True, "model_type": "text", "context_window": 200000, "temperature": 1.0, "price_input": 0.25, "price_output": 1.25},
    # Claude aliases
    "claude-sonnet-4-20250514": {"display_name": "Claude Sonnet 4", "is_multimodal": True, "model_type": "text", "context_window": 200000, "temperature": 1.0, "price_input": 3.0, "price_output": 15.0},

    # DeepSeek models
    "deepseek-chat": {"display_name": "DeepSeek Chat (V3)", "is_multimodal": False, "model_type": "text", "context_window": 65536, "temperature": 1.0, "price_input": 0.27, "price_output": 1.1},
    "deepseek-coder": {"display_name": "DeepSeek Coder", "is_multimodal": False, "model_type": "text", "context_window": 128000, "temperature": 1.0, "price_input": 0.14, "price_output": 0.28},
    "deepseek-reasoner": {"display_name": "DeepSeek Reasoner (R1)", "is_multimodal": False, "model_type": "text", "context_window": 65536, "temperature": 1.0, "price_input": 0.55, "price_output": 2.19},
    "deepseek-v3": {"display_name": "DeepSeek V3", "is_multimodal": False, "model_type": "text", "context_window": 65536, "temperature": 1.0, "price_input": 0.27, "price_output": 1.1},
    "deepseek-v4-flash": {"display_name": "DeepSeek V4 Flash", "is_multimodal": False, "model_type": "text", "context_window": 131072, "temperature": 1.0, "price_input": 0.0, "price_output": 0.0},

    # Qwen models
    "qwen-turbo": {"display_name": "Qwen Turbo", "is_multimodal": False, "model_type": "text", "context_window": 131072, "temperature": 1.0, "price_input": 0.3, "price_output": 0.6},
    "qwen-plus": {"display_name": "Qwen Plus", "is_multimodal": False, "model_type": "text", "context_window": 131072, "temperature": 1.0, "price_input": 0.8, "price_output": 2.0},
    "qwen-max": {"display_name": "Qwen Max", "is_multimodal": False, "model_type": "text", "context_window": 32768, "temperature": 1.0, "price_input": 2.0, "price_output": 6.0},
    "qwen-long": {"display_name": "Qwen Long", "is_multimodal": False, "model_type": "text", "context_window": 10000000, "temperature": 1.0, "price_input": 0.5, "price_output": 2.0},
    "qwen-vl-plus": {"display_name": "Qwen VL Plus", "is_multimodal": True, "model_type": "text", "context_window": 131072, "temperature": 1.0, "price_input": 0.8, "price_output": 2.0},
    "qwen-vl-max": {"display_name": "Qwen VL Max", "is_multimodal": True, "model_type": "text", "context_window": 32768, "temperature": 1.0, "price_input": 2.0, "price_output": 6.0},

    # GLM models (Zhipu)
    "glm-4-plus": {"display_name": "GLM-4 Plus", "is_multimodal": False, "model_type": "text", "context_window": 128000, "temperature": 1.0, "price_input": 0.05, "price_output": 0.05},
    "glm-4-flash": {"display_name": "GLM-4 Flash", "is_multimodal": False, "model_type": "text", "context_window": 128000, "temperature": 1.0, "price_input": 0.0, "price_output": 0.0},
    "glm-4-long": {"display_name": "GLM-4 Long", "is_multimodal": False, "model_type": "text", "context_window": 1000000, "temperature": 1.0, "price_input": 0.001, "price_output": 0.001},
    "glm-4v-plus": {"display_name": "GLM-4V Plus", "is_multimodal": True, "model_type": "text", "context_window": 8192, "temperature": 1.0, "price_input": 0.01, "price_output": 0.01},

    # Doubao models (ByteDance)
    "doubao-pro-32k": {"display_name": "Doubao Pro 32K", "is_multimodal": False, "model_type": "text", "context_window": 32768, "temperature": 1.0, "price_input": 0.8, "price_output": 2.0},
    "doubao-pro-128k": {"display_name": "Doubao Pro 128K", "is_multimodal": False, "model_type": "text", "context_window": 128000, "temperature": 1.0, "price_input": 2.0, "price_output": 6.0},
    "doubao-lite-32k": {"display_name": "Doubao Lite 32K", "is_multimodal": False, "model_type": "text", "context_window": 32768, "temperature": 1.0, "price_input": 0.3, "price_output": 0.6},

    # Gemini models
    "gemini-2.5-pro-preview-05-06": {"display_name": "Gemini 2.5 Pro", "is_multimodal": True, "model_type": "text", "context_window": 1048576, "temperature": 2.0, "price_input": 1.25, "price_output": 10.0},
    "gemini-2.0-flash": {"display_name": "Gemini 2.0 Flash", "is_multimodal": True, "model_type": "text", "context_window": 1048576, "temperature": 2.0, "price_input": 0.1, "price_output": 0.4},
    "gemini-1.5-pro": {"display_name": "Gemini 1.5 Pro", "is_multimodal": True, "model_type": "text", "context_window": 2097152, "temperature": 2.0, "price_input": 1.25, "price_output": 5.0},
    "gemini-1.5-flash": {"display_name": "Gemini 1.5 Flash", "is_multimodal": True, "model_type": "text", "context_window": 1048576, "temperature": 2.0, "price_input": 0.075, "price_output": 0.3},

    # Groq models
    "llama-3.3-70b-versatile": {"display_name": "Llama 3.3 70B", "is_multimodal": False, "model_type": "text", "context_window": 128000, "temperature": 1.0, "price_input": 0.59, "price_output": 0.79},
    "llama-3.1-8b-instant": {"display_name": "Llama 3.1 8B", "is_multimodal": False, "model_type": "text", "context_window": 128000, "temperature": 1.0, "price_input": 0.05, "price_output": 0.08},
    "mixtral-8x7b-32768": {"display_name": "Mixtral 8x7B", "is_multimodal": False, "model_type": "text", "context_window": 32768, "temperature": 1.0, "price_input": 0.24, "price_output": 0.24},

    # Mistral models
    "mistral-large-latest": {"display_name": "Mistral Large", "is_multimodal": False, "model_type": "text", "context_window": 128000, "temperature": 1.0, "price_input": 2.0, "price_output": 6.0},
    "mistral-small-latest": {"display_name": "Mistral Small", "is_multimodal": False, "model_type": "text", "context_window": 128000, "temperature": 1.0, "price_input": 0.1, "price_output": 0.3},
    "pixtral-large-latest": {"display_name": "Pixtral Large", "is_multimodal": True, "model_type": "text", "context_window": 128000, "temperature": 1.0, "price_input": 2.0, "price_output": 6.0},
    "codestral-latest": {"display_name": "Codestral", "is_multimodal": False, "model_type": "text", "context_window": 256000, "temperature": 1.0, "price_input": 0.3, "price_output": 0.9},

    # Moonshot models
    "moonshot-v1-8k": {"display_name": "Moonshot V1 8K", "is_multimodal": False, "model_type": "text", "context_window": 8192, "temperature": 1.0, "price_input": 12.0, "price_output": 12.0},
    "moonshot-v1-32k": {"display_name": "Moonshot V1 32K", "is_multimodal": False, "model_type": "text", "context_window": 32768, "temperature": 1.0, "price_input": 24.0, "price_output": 24.0},
    "moonshot-v1-128k": {"display_name": "Moonshot V1 128K", "is_multimodal": False, "model_type": "text", "context_window": 128000, "temperature": 1.0, "price_input": 60.0, "price_output": 60.0},
    "deepseek-v4-pro": {"display_name": "DeepSeek V4 Pro", "is_multimodal": False, "model_type": "text", "context_window": 131072, "temperature": 1.0, "price_input": 0.0, "price_output": 0.0},
    "deepseek-v4-flash-0324": {"display_name": "DeepSeek V4 Flash 0324", "is_multimodal": False, "model_type": "text", "context_window": 131072, "temperature": 1.0, "price_input": 0.0, "price_output": 0.0},
    "deepseek-v4-0324": {"display_name": "DeepSeek V4 0324", "is_multimodal": False, "model_type": "text", "context_window": 131072, "temperature": 1.0, "price_input": 0.0, "price_output": 0.0},
    "deepseek-r1": {"display_name": "DeepSeek R1", "is_multimodal": False, "model_type": "text", "context_window": 131072, "temperature": 1.0, "price_input": 0.55, "price_output": 2.19},
    "deepseek-v3-0324": {"display_name": "DeepSeek V3 0324", "is_multimodal": False, "model_type": "text", "context_window": 65536, "temperature": 1.0, "price_input": 0.27, "price_output": 1.1},
    # Doubao endpoint models (endpoint IDs are user-specific, but common patterns)
    # GLM endpoint models
    "glm-4": {"display_name": "GLM-4", "is_multimodal": False, "model_type": "text", "context_window": 128000, "temperature": 1.0, "price_input": 0.1, "price_output": 0.1},
    "glm-4v": {"display_name": "GLM-4V", "is_multimodal": True, "model_type": "text", "context_window": 8192, "temperature": 1.0, "price_input": 0.05, "price_output": 0.05},
    # Yi models
    "yi-large": {"display_name": "Yi Large", "is_multimodal": False, "model_type": "text", "context_window": 32768, "temperature": 1.0, "price_input": 0.03, "price_output": 0.03},
    "yi-medium": {"display_name": "Yi Medium", "is_multimodal": False, "model_type": "text", "context_window": 16384, "temperature": 1.0, "price_input": 0.004, "price_output": 0.004},
    # Hunyuan
    "hunyuan-pro": {"display_name": "Hunyuan Pro", "is_multimodal": True, "model_type": "text", "context_window": 32768, "temperature": 1.0, "price_input": 1.0, "price_output": 3.0},
    "hunyuan-standard": {"display_name": "Hunyuan Standard", "is_multimodal": True, "model_type": "text", "context_window": 32768, "temperature": 1.0, "price_input": 0.45, "price_output": 0.5},
    "hunyuan-turbos-latest": {"display_name": "Hunyuan Turbos", "is_multimodal": False, "model_type": "text", "context_window": 32768, "temperature": 1.0, "price_input": 0.0, "price_output": 0.0},
    # ERNIE (Baidu)
    "ernie-4.0-8k": {"display_name": "ERNIE 4.0 8K", "is_multimodal": False, "model_type": "text", "context_window": 8192, "temperature": 1.0, "price_input": 0.12, "price_output": 0.12},
    "ernie-3.5-8k": {"display_name": "ERNIE 3.5 8K", "is_multimodal": False, "model_type": "text", "context_window": 8192, "temperature": 1.0, "price_input": 0.008, "price_output": 0.008},
    "ernie-speed-8k": {"display_name": "ERNIE Speed 8K", "is_multimodal": False, "model_type": "text", "context_window": 8192, "temperature": 1.0, "price_input": 0.0, "price_output": 0.0},
    # Baichuan
    "baichuan4": {"display_name": "Baichuan 4", "is_multimodal": False, "model_type": "text", "context_window": 32768, "temperature": 1.0, "price_input": 0.1, "price_output": 0.1},
    # MiniMax
    "abab6.5s-chat": {"display_name": "Abab 6.5S", "is_multimodal": False, "model_type": "text", "context_window": 1024000, "temperature": 1.0, "price_input": 0.005, "price_output": 0.005},
    # StepFun (Yi STEP)
    "step-2-16k": {"display_name": "Step 2 16K", "is_multimodal": False, "model_type": "text", "context_window": 16384, "temperature": 1.0, "price_input": 0.018, "price_output": 0.018},
    "step-1-flash": {"display_name": "Step 1 Flash", "is_multimodal": False, "model_type": "text", "context_window": 8192, "temperature": 1.0, "price_input": 0.0, "price_output": 0.0},
}


def get_known_model_params(model_id: str) -> dict:
    """Look up known parameters for a model by its ID."""
    if model_id in KNOWN_MODELS:
        return dict(KNOWN_MODELS[model_id])
    # Try partial match (e.g. "deepseek-v4-flash-0324" -> "deepseek-v4-flash")
    for known_id, params in KNOWN_MODELS.items():
        if model_id.startswith(known_id) or known_id.startswith(model_id.split("-0")[0]):
            return dict(params)
    return {}


def detect_model_type(model_id: str) -> str:
    """Detect model type from ID string."""
    mid = model_id.lower()
    if any(k in mid for k in ["embedding", "embed"]):
        return "embedding"
    if any(k in mid for k in ["dall-e", "image", "flux", "stable-diffusion", "midjourney"]):
        return "image"
    if any(k in mid for k in ["tts", "whisper", "speech"]):
        return "tts"
    if any(k in mid for k in ["video", "sora", "kling", "veo"]):
        return "video"
    return "text"
