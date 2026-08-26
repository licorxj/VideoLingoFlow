"""
LiteLLM Adapter - 集成 litellm 作为转发内核
将本项目的负载均衡策略层与 litellm 的 100+ 提供商支持结合
"""
import asyncio
import json
import time
import re
from typing import AsyncGenerator, Any
from dataclasses import dataclass
from app.models.provider import Provider
from app.models.api_key import ApiKey
from app.models.model import Model
from app.utils.crypto import decrypt_value


@dataclass
class LiteLLMConfig:
    """LiteLLM 模型配置"""
    model_name: str  # 暴露给客户端的模型名
    litellm_model: str  # litellm 内部模型标识
    api_key: str
    api_base: str | None = None
    api_version: str | None = None
    extra_params: dict = None

    def to_litellm_params(self) -> dict:
        params = {
            "model": self.litellm_model,
            "api_key": self.api_key,
        }
        if self.api_base:
            params["api_base"] = self.api_base
        if self.api_version:
            params["api_version"] = self.api_version
        if self.extra_params:
            params.update(self.extra_params)
        return params


class LiteLLMAdapter:
    """LiteLLM 适配器"""

    def __init__(self):
        self._model_cache: dict[str, LiteLLMConfig] = {}
        self._cache_time: float = 0
        self._cache_ttl: int = 300  # 5分钟缓存

    def _get_provider_model_key(self, provider: Provider, model: Model) -> str:
        return f"{provider.id}:{model.id}"

    def _provider_protocol_to_litellm(self, provider: Provider, model: Model, api_key: ApiKey) -> str:
        """将 Provider 协议转换为 litellm 模型标识"""
        protocol = provider.protocol.lower()
        model_id = model.model_id

        # 常见提供商映射
        provider_mapping = {
            "openai": "openai",
            "azure": "azure/",
            "anthropic": "anthropic",
            "gemini": "gemini",
            "deepseek": "deepseek",
            "qwen": "openai/qwen",  # 通义千问使用 OpenAI 兼容格式
            "zhipu": "openai/zhipu",  # 智谱
            "moonshot": "openai/moonshot",  # 月之暗面
            "minimax": "openai/minimax",
            "yi": "openai/yi",
            "step": "openai/step",
            "cloudflare": "openai/@cf",
            "groq": "groq/",
            "togetherai": "openai/together",
            "fireworks": "fireworks/",
            "perplexity": "openai/perplexity",
            "ollama": "ollama/",
            "vllm": "openai/",
            "custom": "openai/",
        }

        litellm_prefix = provider_mapping.get(protocol, "openai/")

        # 构建 litellm 模型标识
        if protocol == "azure":
            # Azure: azure/<deployment_name>
            return f"{litellm_prefix}{model_id}"
        elif protocol == "ollama":
            # Ollama: ollama/<model_name>
            return f"{litellm_prefix}{model_id}"
        elif protocol == "gemini":
            # Gemini: gemini/<model_name>
            return f"gemini/{model_id}"
        elif protocol == "anthropic":
            # Anthropic: anthropic/<model_name>
            return f"anthropic/{model_id}"
        else:
            # OpenAI兼容: openai/<model_name> 或 provider/model
            return f"{litellm_prefix}{model_id}"

    def build_model_config(
        self, provider: Provider, model: Model, api_key: ApiKey
    ) -> LiteLLMConfig:
        """构建单个模型的 litellm 配置"""
        cache_key = self._get_provider_model_key(provider, model)

        # 检查缓存
        if cache_key in self._model_cache:
            cached = self._model_cache[cache_key]
            if time.time() - self._cache_time < self._cache_ttl:
                return cached

        # 解密 API key
        real_key = decrypt_value(api_key.key_value)
        base_url = provider.base_url.rstrip("/") if provider.base_url else None

        # 获取 litellm 模型标识
        litellm_model = self._provider_protocol_to_litellm(provider, model, api_key)

        # 构建额外参数
        extra_params = {}
        if provider.protocol.lower() == "azure":
            extra_params["api_version"] = provider.extra_config.get("api_version", "2024-02-01") if provider.extra_config else "2024-02-01"

        # 模型特定参数
        if model.extra_params:
            try:
                extra_params.update(json.loads(model.extra_params) if isinstance(model.extra_params, str) else model.extra_params)
            except (json.JSONDecodeError, TypeError):
                pass

        config = LiteLLMConfig(
            model_name=f"{provider.name}/{model.model_id}",  # 暴露名
            litellm_model=litellm_model,
            api_key=real_key,
            api_base=base_url,
            extra_params=extra_params if extra_params else None,
        )

        self._model_cache[cache_key] = config
        self._cache_time = time.time()
        return config

    async def completion(
        self,
        model: str,
        messages: list,
        is_stream: bool = False,
        timeout: int = 120,
        **kwargs,
    ) -> Any:
        """
        使用 litellm 发起补全请求

        Args:
            model: 完整模型标识 (provider/model_id)
            messages: 消息列表
            is_stream: 是否流式
            timeout: 超时秒数
            **kwargs: 其他 litellm 参数

        Returns:
            litellm 响应对象
        """
        import litellm

        # 配置超时
        litellm.timeout = timeout

        # 构建 litellm 参数
        params = {
            "model": model,
            "messages": messages,
            "stream": is_stream,
            "custom_llm_provider": self._extract_provider(model),
            **kwargs,
        }

        # 移除 None 值
        params = {k: v for k, v in params.items() if v is not None}

        # 调用 litellm
        response = await litellm.acompletion(**params)
        return response

    async def completion_stream(
        self,
        model: str,
        messages: list,
        timeout: int = 120,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """
        使用 litellm 发起流式补全请求

        Args:
            model: 完整模型标识
            messages: 消息列表
            timeout: 超时秒数
            **kwargs: 其他 litellm 参数

        Yields:
            SSE 格式的数据块
        """
        import litellm

        litellm.timeout = timeout

        params = {
            "model": model,
            "messages": messages,
            "stream": True,
            "custom_llm_provider": self._extract_provider(model),
            **kwargs,
        }
        params = {k: v for k, v in params.items() if v is not None}

        response = await litellm.acompletion(**params)

        async for chunk in response:
            # litellm 流式响应已经是 OpenAI 格式
            delta = chunk.choices[0].delta
            if delta:
                content = delta.content or ""
                if content:
                    yield f'data: {json.dumps({"choices": [{"delta": {"content": content}}]})}\n\n'

            # 检查是否完成
            if chunk.choices[0].finish_reason:
                yield "data: [DONE]\n\n"

    async def multi_forward(
        self,
        requests: list[dict],
        timeout: int = 120,
    ) -> list[dict]:
        """
        同时向多个端点发送请求

        Args:
            requests: 请求列表，每项包含 model, messages, 等参数
            timeout: 超时秒数

        Returns:
            所有响应的列表
        """
        import litellm

        litellm.timeout = timeout

        async def single_request(req: dict) -> dict:
            try:
                params = {
                    "model": req["model"],
                    "messages": req["messages"],
                    "stream": req.get("stream", False),
                    "custom_llm_provider": self._extract_provider(req["model"]),
                }
                # 添加额外参数
                for key in ["temperature", "max_tokens", "top_p", "frequency_penalty",
                           "presence_penalty", "stop", "response_format"]:
                    if key in req:
                        params[key] = req[key]

                params = {k: v for k, v in params.items() if v is not None}

                if params.get("stream"):
                    # 流式请求
                    responses = []
                    async for chunk in litellm.acompletion(**params):
                        delta = chunk.choices[0].delta
                        content = delta.content if delta else ""
                        responses.append(content)
                    return {"success": True, "content": "".join(responses)}
                else:
                    response = await litellm.acompletion(**params)
                    content = response.choices[0].message.content
                    return {"success": True, "content": content}
            except Exception as e:
                return {"success": False, "error": str(e)}

        # 并发执行所有请求
        tasks = [single_request(req) for req in requests]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理异常
        return [
            r if isinstance(r, dict) else {"success": False, "error": str(r)}
            for r in results
        ]

    def _extract_provider(self, model: str) -> str | None:
        """从模型标识中提取提供商"""
        # litellm 支持的提供商
        providers = [
            "openai", "azure", "anthropic", "gemini", "deepseek", "groq",
            "ollama", "vllm", "togetherai", "fireworks", "perplexity",
            "cloudflare", "huggingface", "replicate", "sagemaker", "vertex_ai",
        ]

        for provider in providers:
            if model.startswith(f"{provider}/"):
                return provider

        return None

    def clear_cache(self):
        """清除配置缓存"""
        self._model_cache.clear()
        self._cache_time = 0


# 全局实例
_litellm_adapter: LiteLLMAdapter | None = None


def get_litellm_adapter() -> LiteLLMAdapter:
    """获取全局 litellm 适配器实例"""
    global _litellm_adapter
    if _litellm_adapter is None:
        _litellm_adapter = LiteLLMAdapter()
    return _litellm_adapter


async def litellm_completion(
    model: str,
    messages: list,
    is_stream: bool = False,
    timeout: int = 120,
    **kwargs,
) -> Any:
    """便捷函数：使用全局适配器发起请求"""
    adapter = get_litellm_adapter()
    return await adapter.completion(model, messages, is_stream, timeout, **kwargs)


async def litellm_completion_stream(
    model: str,
    messages: list,
    timeout: int = 120,
    **kwargs,
) -> AsyncGenerator[str, None]:
    """便捷函数：使用全局适配器发起流式请求"""
    adapter = get_litellm_adapter()
    async for chunk in adapter.completion_stream(model, messages, timeout, **kwargs):
        yield chunk


async def litellm_multi_forward(
    requests: list[dict],
    timeout: int = 120,
) -> list[dict]:
    """便捷函数：同时向多个端点发送请求"""
    adapter = get_litellm_adapter()
    return await adapter.multi_forward(requests, timeout)
