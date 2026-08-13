"""LLM API: presets, test, streaming, batch."""
import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from backend.config.config_manager import config
from backend.llm.llm_client import get_llm_client

router = APIRouter()


@router.get("/config")
async def get_llm_config():
    """Get current LLM configuration."""
    return {
        "base_url": config.get("llm.base_url") or "",
        "api_key": config.get("llm.api_key") or "",
        "max_concurrent": config.get("llm.max_concurrent") or 10,
        "timeout": config.get("llm.timeout") or 120,
        "step_models": config.get("llm.step_models") or {},
    }


@router.get("/presets")
async def get_llm_presets():
    """Get LLM connection presets (derived from current config)."""
    use_router = config.get("llm.use_router")
    if use_router:
        base_url = config.get("llm.router_url") or ""
        api_key = config.get("llm.router_api_key") or ""
    else:
        base_url = config.get("llm.base_url") or ""
        api_key = config.get("llm.api_key") or ""
    step_models = config.get("llm.step_models") or {}
    presets = [
        {
            "id": "default",
            "name": "当前 LLM 连接",
            "base_url": base_url,
            "api_key": (api_key[:4] + "****") if api_key else "",
            "use_router": bool(use_router),
            "default_model": step_models.get("default_model") or "",
            "models": [
                {"step": step, "model": model}
                for step, model in step_models.items()
                if step != "default_model" and model
            ],
        }
    ]
    return {"presets": presets}


class TestRequest(BaseModel):
    step_name: str = "test"
    prompt: str = 'Respond with JSON: {"message": "success"}'


@router.post("/test")
async def test_llm(req: TestRequest):
    """Test LLM connectivity with a simple prompt."""
    try:
        llm = get_llm_client()
        api_cfg = llm._get_api_config(req.step_name)
        masked_key = api_cfg["api_key"][:4] + "****" + api_cfg["api_key"][-4:] if len(api_cfg["api_key"]) > 8 else "****"

        # 展示修正后的实际请求 URL
        client = llm._make_client(api_cfg)
        actual_url = str(client.base_url).rstrip("/")

        print(f"\n{'='*60}")
        print(f"[LLM Test] step_name:  {req.step_name}")
        print(f"[LLM Test] config_url: {api_cfg['base_url']}")
        print(f"[LLM Test] actual_url: {actual_url}")
        print(f"[LLM Test] api_key:    {masked_key}")
        print(f"[LLM Test] model:      {api_cfg['model']}")
        print(f"[LLM Test] timeout:    {api_cfg['timeout']}")
        print(f"[LLM Test] prompt:     {req.prompt}")
        print(f"{'='*60}")

        result = llm.chat(
            req.step_name, req.prompt, response_json=True, log=False
        )

        print(f"[LLM Test] Response:")
        print(f"  {json.dumps(result, ensure_ascii=False, indent=2) if isinstance(result, dict) else str(result)}")
        print(f"{'='*60}\n")
        return {"success": True, "result": result}
    except Exception as e:
        print(f"[LLM Test] ERROR: {e}")
        print(f"{'='*60}\n")
        return {"success": False, "error": str(e)}


class ChatRequest(BaseModel):
    step_name: str
    prompt: str
    messages: Optional[list] = None
    system_prompt: Optional[str] = None
    response_json: bool = True


@router.post("/chat")
async def chat(req: ChatRequest):
    """Send a chat completion request."""
    try:
        llm = get_llm_client()
        result = llm.chat(
            req.step_name,
            req.prompt,
            messages=req.messages,
            response_json=req.response_json,
            system_prompt=req.system_prompt,
        )
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


class StreamRequest(BaseModel):
    step_name: str
    prompt: str
    system_prompt: Optional[str] = None


@router.post("/stream")
async def stream_chat(req: StreamRequest):
    """Stream a chat completion response."""
    llm = get_llm_client()

    def generate():
        try:
            for chunk in llm.chat(
                req.step_name,
                req.prompt,
                system_prompt=req.system_prompt,
                response_json=False,
                stream=True,
                log=False,
            ):
                yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


class BatchRequest(BaseModel):
    requests: list[ChatRequest]


@router.post("/batch")
async def batch_chat(req: BatchRequest):
    """Execute multiple LLM requests concurrently."""
    try:
        llm = get_llm_client()
        batch = [
            {
                "step_name": r.step_name,
                "prompt": r.prompt,
                "response_json": r.response_json,
            }
            for r in req.requests
        ]
        results = llm.batch_chat(batch)
        return {"success": True, "results": results}
    except Exception as e:
        return {"success": False, "error": str(e)}
