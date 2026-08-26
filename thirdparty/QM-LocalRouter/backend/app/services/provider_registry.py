"""
提供商注册表 - LiteLLM 支持的所有提供商信息

用于前端展示、配置引导和协议适配
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ProviderInfo:
    """提供商信息"""
    id: str                    # 唯一标识 (与 litellm provider name 对应)
    name: str                  # 显示名称
    protocol: str              # 协议类型: openai, azure, anthropic, gemini, custom, ollama
    icon: str                  # 图标 (emoji)
    color: str                 # 主题色
    docs_url: str              # 官方文档链接
    api_key_env: str           # 环境变量名 (如 OPENAI_API_KEY)
    base_url_hint: str         # base_url 提示
    supports_streaming: bool    # 是否支持流式
    supports_functions: bool    # 是否支持 function calling
    supports_vision: bool      # 是否支持视觉
    supports_json_mode: bool    # 是否支持 JSON 模式
    region_required: bool      # 是否需要区域配置
    auth_type: str             # 认证类型: api_key, oauth, aws_sig, vertex


# LiteLLM 支持的提供商注册表
PROVIDER_REGISTRY: dict[str, ProviderInfo] = {
    # ============================================================
    # OpenAI 系列
    # ============================================================
    "openai": ProviderInfo(
        id="openai",
        name="OpenAI",
        protocol="openai",
        icon="🤖",
        color="#10A37F",
        docs_url="https://platform.openai.com/docs/api-reference",
        api_key_env="OPENAI_API_KEY",
        base_url_hint="https://api.openai.com/v1",
        supports_streaming=True,
        supports_functions=True,
        supports_vision=True,
        supports_json_mode=True,
        region_required=False,
        auth_type="api_key",
    ),

    "azure": ProviderInfo(
        id="azure",
        name="Azure OpenAI",
        protocol="azure",
        icon="☁️",
        color="#0078D4",
        docs_url="https://learn.microsoft.com/en-us/azure/ai-services/openai/",
        api_key_env="AZURE_API_KEY",
        base_url_hint="https://YOUR_RESOURCE.openai.azure.com",
        supports_streaming=True,
        supports_functions=True,
        supports_vision=True,
        supports_json_mode=True,
        region_required=True,
        auth_type="api_key",
    ),

    "azure_ai": ProviderInfo(
        id="azure_ai",
        name="Azure AI Studio",
        protocol="azure",
        icon="☁️",
        color="#0078D4",
        docs_url="https://learn.microsoft.com/en-us/azure/ai-studio/",
        api_key_env="AZURE_AI_KEY",
        base_url_hint="https://YOUR_RESOURCE.services.ai.azure.com",
        supports_streaming=True,
        supports_functions=True,
        supports_vision=True,
        supports_json_mode=True,
        region_required=True,
        auth_type="api_key",
    ),

    # ============================================================
    # Anthropic 系列
    # ============================================================
    "anthropic": ProviderInfo(
        id="anthropic",
        name="Anthropic",
        protocol="anthropic",
        icon="🧠",
        color="#D4A574",
        docs_url="https://docs.anthropic.com/claude/reference",
        api_key_env="ANTHROPIC_API_KEY",
        base_url_hint="https://api.anthropic.com",
        supports_streaming=True,
        supports_functions=True,
        supports_vision=True,
        supports_json_mode=True,
        region_required=False,
        auth_type="api_key",
    ),

    "vertex_ai": ProviderInfo(
        id="vertex_ai",
        name="Vertex AI (Google Cloud)",
        protocol="vertex",
        icon="🌐",
        color="#4285F4",
        docs_url="https://cloud.google.com/vertex-ai/docs/startup-guides",
        api_key_env="VERTEXAI_PROJECT",
        base_url_hint="https://{location}-aiplatform.googleapis.com",
        supports_streaming=True,
        supports_functions=True,
        supports_vision=True,
        supports_json_mode=True,
        region_required=True,
        auth_type="oauth",
    ),

    "gemini": ProviderInfo(
        id="gemini",
        name="Google AI Studio",
        protocol="gemini",
        icon="✨",
        color="#4285F4",
        docs_url="https://ai.google.dev/docs",
        api_key_env="GEMINI_API_KEY",
        base_url_hint="https://generativelanguage.googleapis.com",
        supports_streaming=True,
        supports_functions=True,
        supports_vision=True,
        supports_json_mode=True,
        region_required=False,
        auth_type="api_key",
    ),

    # ============================================================
    # 国内厂商
    # ============================================================
    "deepseek": ProviderInfo(
        id="deepseek",
        name="DeepSeek",
        protocol="openai",
        icon="🔮",
        color="#6B4EE6",
        docs_url="https://platform.deepseek.com/docs",
        api_key_env="DEEPSEEK_API_KEY",
        base_url_hint="https://api.deepseek.com",
        supports_streaming=True,
        supports_functions=True,
        supports_vision=False,
        supports_json_mode=True,
        region_required=False,
        auth_type="api_key",
    ),

    "qwen": ProviderInfo(
        id="qwen",
        name="通义千问 (Qwen)",
        protocol="openai",
        icon="🌟",
        color="#FF6B00",
        docs_url="https://help.aliyun.com/zh/dashscope/",
        api_key_env="DASHSCOPE_API_KEY",
        base_url_hint="https://dashscope.aliyuncs.com/compatible-mode/v1",
        supports_streaming=True,
        supports_functions=True,
        supports_vision=True,
        supports_json_mode=True,
        region_required=False,
        auth_type="api_key",
    ),

    "zhipu": ProviderInfo(
        id="zhipu",
        name="智谱 AI (GLM)",
        protocol="openai",
        icon="📊",
        color="#4B7BE5",
        docs_url="https://open.bigmodel.cn/dev/api",
        api_key_env="ZHIPU_API_KEY",
        base_url_hint="https://open.bigmodel.cn/api/paas/v4",
        supports_streaming=True,
        supports_functions=True,
        supports_vision=True,
        supports_json_mode=True,
        region_required=False,
        auth_type="api_key",
    ),

    "moonshot": ProviderInfo(
        id="moonshot",
        name="月之暗面 (Moonshot)",
        protocol="openai",
        icon="🌙",
        color="#4A90D9",
        docs_url="https://platform.moonshot.cn/docs",
        api_key_env="MOONSHOT_API_KEY",
        base_url_hint="https://api.moonshot.cn/v1",
        supports_streaming=True,
        supports_functions=True,
        supports_vision=True,
        supports_json_mode=True,
        region_required=False,
        auth_type="api_key",
    ),

    "minimax": ProviderInfo(
        id="minimax",
        name="MiniMax",
        protocol="openai",
        icon="🎯",
        color="#00D4AA",
        docs_url="https://www.minimaxi.com/document",
        api_key_env="MINIMAX_API_KEY",
        base_url_hint="https://api.minimax.chat/v1",
        supports_streaming=True,
        supports_functions=True,
        supports_vision=True,
        supports_json_mode=True,
        region_required=False,
        auth_type="api_key",
    ),

    "yi": ProviderInfo(
        id="yi",
        name="零一万物 (Yi)",
        protocol="openai",
        icon="💡",
        color="#FFD700",
        docs_url="https://platform.lingyiwanwu.com/docs",
        api_key_env="YI_API_KEY",
        base_url_hint="https://api.lingyiwanwu.com/v1",
        supports_streaming=True,
        supports_functions=True,
        supports_vision=True,
        supports_json_mode=True,
        region_required=False,
        auth_type="api_key",
    ),

    "step": ProviderInfo(
        id="step",
        name="阶跃星辰 (Step)",
        protocol="openai",
        icon="🚀",
        color="#FF4081",
        docs_url="https://platform.stepfun.com/docs",
        api_key_env="STEPPING_API_KEY",
        base_url_hint="https://api.stepfun.com/v1",
        supports_streaming=True,
        supports_functions=True,
        supports_vision=True,
        supports_json_mode=True,
        region_required=False,
        auth_type="api_key",
    ),

    "volcengine": ProviderInfo(
        id="volcengine",
        name="火山引擎 (Volcengine)",
        protocol="openai",
        icon="🌋",
        color="#FC521F",
        docs_url="https://www.volcengine.com/docs/82379/1263482",
        api_key_env="VOLCENGINE_API_KEY",
        base_url_hint="https://ark.cn-beijing.volces.com/api/v3",
        supports_streaming=True,
        supports_functions=True,
        supports_vision=True,
        supports_json_mode=True,
        region_required=True,
        auth_type="api_key",
    ),

    "siliconflow": ProviderInfo(
        id="siliconflow",
        name="SiliconFlow",
        protocol="openai",
        icon="⚡",
        color="#6C5CE7",
        docs_url="https://docs.siliconflow.cn/",
        api_key_env="SILICONFLOW_API_KEY",
        base_url_hint="https://api.siliconflow.cn/v1",
        supports_streaming=True,
        supports_functions=True,
        supports_vision=True,
        supports_json_mode=True,
        region_required=False,
        auth_type="api_key",
    ),

    "togetherai": ProviderInfo(
        id="togetherai",
        name="Together AI",
        protocol="openai",
        icon="🤝",
        color="#5B5EED",
        docs_url="https://docs.together.ai/",
        api_key_env="TOGETHERAI_API_KEY",
        base_url_hint="https://api.together.xyz/v1",
        supports_streaming=True,
        supports_functions=True,
        supports_vision=True,
        supports_json_mode=True,
        region_required=False,
        auth_type="api_key",
    ),

    "fireworks": ProviderInfo(
        id="fireworks",
        name="Fireworks AI",
        protocol="openai",
        icon="🎆",
        color="#F97316",
        docs_url="https://docs.fireworks.ai/",
        api_key_env="FIREWORKS_API_KEY",
        base_url_hint="https://api.fireworks.ai/inference/v1",
        supports_streaming=True,
        supports_functions=True,
        supports_vision=True,
        supports_json_mode=True,
        region_required=False,
        auth_type="api_key",
    ),

    # ============================================================
    # AWS 系列
    # ============================================================
    "bedrock": ProviderInfo(
        id="bedrock",
        name="AWS Bedrock",
        protocol="aws_bedrock",
        icon="🗻",
        color="#FF9900",
        docs_url="https://docs.aws.amazon.com/bedrock/",
        api_key_env="AWS_ACCESS_KEY_ID",
        base_url_hint="bedrock.{region}.amazonaws.com",
        supports_streaming=True,
        supports_functions=True,
        supports_vision=True,
        supports_json_mode=True,
        region_required=True,
        auth_type="aws_sig",
    ),

    "sagemaker": ProviderInfo(
        id="sagemaker",
        name="AWS Sagemaker",
        protocol="sagemaker",
        icon="📦",
        color="#FF9900",
        docs_url="https://docs.aws.amazon.com/sagemaker/",
        api_key_env="AWS_ACCESS_KEY_ID",
        base_url_hint="https://runtime.sagemaker.{region}.amazonaws.com",
        supports_streaming=True,
        supports_functions=False,
        supports_vision=False,
        supports_json_mode=True,
        region_required=True,
        auth_type="aws_sig",
    ),

    # ============================================================
    # 其他海外厂商
    # ============================================================
    "groq": ProviderInfo(
        id="groq",
        name="Groq",
        protocol="openai",
        icon="⚡",
        color="#2ECC71",
        docs_url="https://console.groq.com/docs",
        api_key_env="GROQ_API_KEY",
        base_url_hint="https://api.groq.com/openai/v1",
        supports_streaming=True,
        supports_functions=True,
        supports_vision=False,
        supports_json_mode=True,
        region_required=False,
        auth_type="api_key",
    ),

    "cohere": ProviderInfo(
        id="cohere",
        name="Cohere",
        protocol="openai",
        icon="🌊",
        color="#1B4965",
        docs_url="https://docs.cohere.com/",
        api_key_env="COHERE_API_KEY",
        base_url_hint="https://api.cohere.ai/v1",
        supports_streaming=True,
        supports_functions=True,
        supports_vision=False,
        supports_json_mode=True,
        region_required=False,
        auth_type="api_key",
    ),

    "mistral": ProviderInfo(
        id="mistral",
        name="Mistral AI",
        protocol="openai",
        icon="🌬️",
        color="#EB6235",
        docs_url="https://docs.mistral.ai/",
        api_key_env="MISTRAL_API_KEY",
        base_url_hint="https://api.mistral.ai/v1",
        supports_streaming=True,
        supports_functions=True,
        supports_vision=False,
        supports_json_mode=True,
        region_required=False,
        auth_type="api_key",
    ),

    "perplexity": ProviderInfo(
        id="perplexity",
        name="Perplexity",
        protocol="openai",
        icon="🔍",
        color="#20B4F5",
        docs_url="https://docs.perplexity.ai/",
        api_key_env="PERPLEXITY_API_KEY",
        base_url_hint="https://api.perplexity.ai",
        supports_streaming=True,
        supports_functions=True,
        supports_vision=False,
        supports_json_mode=True,
        region_required=False,
        auth_type="api_key",
    ),

    "huggingface": ProviderInfo(
        id="huggingface",
        name="HuggingFace",
        protocol="huggingface",
        icon="🤗",
        color="#FFD21E",
        docs_url="https://huggingface.co/docs/inference-endpoints/",
        api_key_env="HF_TOKEN",
        base_url_hint="https://api-inference.huggingface.co/v1",
        supports_streaming=True,
        supports_functions=False,
        supports_vision=False,
        supports_json_mode=False,
        region_required=False,
        auth_type="api_key",
    ),

    "replicate": ProviderInfo(
        id="replicate",
        name="Replicate",
        protocol="replicate",
        icon="🔄",
        color="#D32768",
        docs_url="https://replicate.com/docs",
        api_key_env="REPLICATE_API_TOKEN",
        base_url_hint="https://api.replicate.com/v1",
        supports_streaming=True,
        supports_functions=False,
        supports_vision=False,
        supports_json_mode=False,
        region_required=False,
        auth_type="api_key",
    ),

    "cloudflare": ProviderInfo(
        id="cloudflare",
        name="Cloudflare Workers AI",
        protocol="openai",
        icon="☁️",
        color="#F6821F",
        docs_url="https://developers.cloudflare.com/workers-ai/",
        api_key_env="CF_API_TOKEN",
        base_url_hint="https://api.cloudflare.com/client/v4/ai",
        supports_streaming=True,
        supports_functions=False,
        supports_vision=False,
        supports_json_mode=False,
        region_required=False,
        auth_type="api_key",
    ),

    # ============================================================
    # 本地部署
    # ============================================================
    "ollama": ProviderInfo(
        id="ollama",
        name="Ollama (本地)",
        protocol="ollama",
        icon="🏠",
        color="#83CC18",
        docs_url="https://github.com/ollama/ollama",
        api_key_env="",
        base_url_hint="http://localhost:11434",
        supports_streaming=True,
        supports_functions=False,
        supports_vision=False,
        supports_json_mode=False,
        region_required=False,
        auth_type="api_key",
    ),

    "vllm": ProviderInfo(
        id="vllm",
        name="vLLM (本地)",
        protocol="openai",
        icon="⚙️",
        color="#9D4EDD",
        docs_url="https://docs.vllm.ai/",
        api_key_env="",
        base_url_hint="http://localhost:8000/v1",
        supports_streaming=True,
        supports_functions=True,
        supports_vision=False,
        supports_json_mode=True,
        region_required=False,
        auth_type="api_key",
    ),

    # ============================================================
    # 其他
    # ============================================================
    "databricks": ProviderInfo(
        id="databricks",
        name="Databricks",
        protocol="openai",
        icon="🏢",
        color="#FF3621",
        docs_url="https://docs.databricks.com/en/general/genai/endpoint-management.html",
        api_key_env="DATABRICKS_API_KEY",
        base_url_hint="https://{workspace}.cloud.databricks.com/serving-endpoints",
        supports_streaming=True,
        supports_functions=True,
        supports_vision=False,
        supports_json_mode=True,
        region_required=True,
        auth_type="api_key",
    ),

    "watsonx": ProviderInfo(
        id="watsonx",
        name="IBM watsonx.ai",
        protocol="openai",
        icon="💧",
        color="#0078D4",
        docs_url="https://www.ibm.com/docs/en/watsonx",
        api_key_env="WATSONX_APIKEY",
        base_url_hint="https://{region}.ml.cloud.ibm.com",
        supports_streaming=True,
        supports_functions=True,
        supports_vision=False,
        supports_json_mode=True,
        region_required=True,
        auth_type="api_key",
    ),

    "nvidia_nim": ProviderInfo(
        id="nvidia_nim",
        name="NVIDIA NIM",
        protocol="openai",
        icon="🎮",
        color="#76B900",
        docs_url="https://docs.nvidia.com/nim/",
        api_key_env="NVIDIA_API_KEY",
        base_url_hint="https://integrate.api.nvidia.com/v1",
        supports_streaming=True,
        supports_functions=True,
        supports_vision=False,
        supports_json_mode=True,
        region_required=False,
        auth_type="api_key",
    ),

    "cerebras": ProviderInfo(
        id="cerebras",
        name="Cerebras",
        protocol="openai",
        icon="🧮",
        color="#00B4C8",
        docs_url="https://inference-docs.cerebras.ai/",
        api_key_env="CEREBRAS_API_KEY",
        base_url_hint="https://api.cerebras.ai/v1",
        supports_streaming=True,
        supports_functions=True,
        supports_vision=False,
        supports_json_mode=True,
        region_required=False,
        auth_type="api_key",
    ),
}


def get_provider_info(provider_id: str) -> Optional[ProviderInfo]:
    """获取提供商信息"""
    return PROVIDER_REGISTRY.get(provider_id)


def get_all_providers() -> dict[str, ProviderInfo]:
    """获取所有提供商"""
    return PROVIDER_REGISTRY.copy()


def get_providers_by_protocol(protocol: str) -> dict[str, ProviderInfo]:
    """按协议筛选提供商"""
    return {
        k: v for k, v in PROVIDER_REGISTRY.items()
        if v.protocol == protocol
    }


def search_providers(keyword: str) -> dict[str, ProviderInfo]:
    """搜索提供商 (按名称)"""
    keyword = keyword.lower()
    return {
        k: v for k, v in PROVIDER_REGISTRY.items()
        if keyword in v.name.lower() or keyword in v.id.lower()
    }
