from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class _Base(BaseModel):
    model_config = {"protected_namespaces": ()}


# -- Provider --
class ProviderCreate(_Base):
    name: str = Field(..., max_length=100)
    protocol: str = Field(default="openai", pattern=r"^(openai|gemini|claude|custom)$")
    base_url: str = Field(..., max_length=500)
    description: str = ""
    icon: str = ""
    homepage: str = ""
    is_active: bool = True


class ProviderUpdate(_Base):
    name: Optional[str] = None
    protocol: Optional[str] = None
    base_url: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    homepage: Optional[str] = None
    is_active: Optional[bool] = None


class ProviderOut(_Base):
    id: int
    name: str
    protocol: str
    base_url: str
    description: str
    icon: str = ""
    homepage: str = ""
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# -- ApiKey --
class ApiKeyCreate(_Base):
    provider_id: int
    key_value: str = Field(..., max_length=500)
    alias: str = ""
    weight: int = Field(default=1, ge=0)


class ApiKeyUpdate(_Base):
    alias: Optional[str] = None
    status: Optional[str] = None
    weight: Optional[int] = None


class ApiKeyOut(_Base):
    id: int
    provider_id: int
    key_masked: str = ""
    key_value: str = ""
    alias: str
    status: str
    weight: int
    last_used_at: Optional[datetime] = None
    last_error: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ApiKeyTestResult(_Base):
    success: bool
    message: str
    latency_ms: Optional[int] = None


class BatchTestResult(_Base):
    total: int
    success: int
    failed: int
    results: list = []


class BatchDeleteResult(_Base):
    deleted: int


# -- Model --
class ModelCreate(_Base):
    provider_id: int
    model_id: str = Field(..., max_length=200)
    display_name: str = ""
    is_active: bool = True
    is_multimodal: bool = False
    model_type: str = Field(default="text", pattern=r"^(text|image|video|tts|embedding|audio)$")
    context_window: Optional[int] = None
    temperature: Optional[float] = None
    price_input: Optional[float] = None
    price_output: Optional[float] = None


class ModelUpdate(_Base):
    model_id: Optional[str] = None
    display_name: Optional[str] = None
    is_active: Optional[bool] = None
    is_multimodal: Optional[bool] = None
    model_type: Optional[str] = None
    context_window: Optional[int] = None
    temperature: Optional[float] = None
    price_input: Optional[float] = None
    price_output: Optional[float] = None
    status: Optional[str] = None
    last_error: Optional[str] = None


class ModelOut(_Base):
    id: int
    provider_id: int
    model_id: str
    display_name: str
    is_active: bool
    is_multimodal: bool = False
    model_type: str = "text"
    context_window: Optional[int] = None
    temperature: Optional[float] = None
    price_input: Optional[float] = None
    price_output: Optional[float] = None
    status: str = "untested"
    last_error: str = ""
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class FetchModelItem(_Base):
    model_id: str
    display_name: str
    is_multimodal: bool = False
    model_type: str = "text"
    context_window: Optional[int] = None
    temperature: Optional[float] = None
    price_input: Optional[float] = None
    price_output: Optional[float] = None
    already_added: bool = False


class ModelTestResult(_Base):
    model_id: str
    success: bool
    message: str
    latency_ms: Optional[int] = None


# -- Strategy --
class StrategyRuleCreate(_Base):
    provider_id: int
    model_id: int
    priority: int = 0
    weight: int = 1
    is_active: bool = True


class StrategyRuleUpdate(_Base):
    priority: Optional[int] = None
    weight: Optional[int] = None
    is_active: Optional[bool] = None


class StrategyRuleOut(_Base):
    id: int
    strategy_id: int
    provider_id: int
    model_id: int
    priority: int
    weight: int
    is_active: bool
    model_name: Optional[str] = None

    class Config:
        from_attributes = True


class StrategyCreate(_Base):
    name: str = Field(..., max_length=100)
    description: str = ""
    lb_strategy: str = Field(default="round_robin", pattern=r"^(round_robin|weighted|random|failover|priority|token_threshold)$")
    key_strategy: str = Field(default="round_robin", pattern=r"^(round_robin|random|failover)$")
    key_switch_mode: str = Field(default="none", pattern=r"^(none|rpm_threshold|count_threshold)$")
    key_rpm_threshold: int = 0
    key_count_threshold: int = 0
    rule_token_threshold: int = 0
    rule_token_period: str = "per_day"
    is_active: bool = True
    timeout: int = 120
    retry_count: int = 2
    rules: list[StrategyRuleCreate] = []


class StrategyUpdate(_Base):
    name: Optional[str] = None
    description: Optional[str] = None
    lb_strategy: Optional[str] = None
    key_strategy: Optional[str] = None
    key_switch_mode: Optional[str] = None
    key_rpm_threshold: Optional[int] = None
    key_count_threshold: Optional[int] = None
    rule_token_threshold: Optional[int] = None
    rule_token_period: Optional[str] = None
    is_active: Optional[bool] = None
    timeout: Optional[int] = None
    retry_count: Optional[int] = None
    rules: Optional[list[StrategyRuleCreate]] = None


class StrategyOut(_Base):
    id: int
    name: str
    description: str
    lb_strategy: str
    key_strategy: str = "round_robin"
    key_switch_mode: str = "none"
    key_rpm_threshold: int = 0
    key_count_threshold: int = 0
    rule_token_threshold: int = 0
    rule_token_period: str = "per_day"
    is_active: bool
    timeout: int
    retry_count: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    rules: list[StrategyRuleOut] = []

    class Config:
        from_attributes = True


class StrategyTestResult(_Base):
    success: bool
    message: str
    latency_ms: Optional[int] = None
    provider_used: Optional[str] = None
    model_used: Optional[str] = None


# -- Logs --
class LogOut(_Base):
    id: int
    strategy_id: Optional[int]
    provider_id: Optional[int]
    api_key_id: Optional[int]
    model_used: str
    status_code: Optional[int]
    latency_ms: Optional[int]
    is_stream: bool
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    error_message: Optional[str]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


# -- Dashboard --
class DashboardStats(_Base):
    total_requests: int = 0
    success_count: int = 0
    error_count: int = 0
    success_rate: float = 0.0
    avg_latency_ms: float = 0.0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    active_strategies: int = 0
    active_providers: int = 0
    active_keys: int = 0


# -- Common --
class PaginatedResponse(_Base):
    items: list
    total: int
    page: int
    page_size: int
