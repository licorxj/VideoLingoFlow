"""
Protocol adapter: converts OpenAI-format requests to upstream provider formats
and converts streaming responses back to OpenAI format. Multimodal message
content (text / image_url / input_audio) is converted where the target
protocol supports it.
"""
import json
import uuid
import time


def _iter_content_blocks(content) -> list[dict]:
    """Normalize OpenAI message content into a list of content blocks.

    Plain strings become a single text block; arrays pass through as-is.
    """
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return [{"type": "text", "text": content}] if content else []


def _parse_data_url(url: str) -> tuple[str, str] | None:
    """data:image/png;base64,xxx -> (mime_type, base64_data)."""
    if not url.startswith("data:"):
        return None
    try:
        header, data = url.split(",", 1)
        mime = header[5:].split(";", 1)[0] or "application/octet-stream"
        return mime, data
    except ValueError:
        return None


def _convert_openai_content_to_claude(content) -> list[dict]:
    """OpenAI content blocks -> Claude content blocks.

    image_url -> type:image source (base64 for data URLs, url source for remote).
    input_audio is not supported by Claude and is skipped.
    """
    blocks = []
    for b in _iter_content_blocks(content):
        btype = b.get("type", "text")
        if btype == "text":
            blocks.append({"type": "text", "text": b.get("text", "")})
        elif btype == "image_url":
            url = (b.get("image_url") or {}).get("url", "")
            data = _parse_data_url(url)
            if data:
                blocks.append({"type": "image", "source": {"type": "base64", "media_type": data[0], "data": data[1]}})
            elif url.startswith("http"):
                blocks.append({"type": "image", "source": {"type": "url", "url": url}})
        elif btype == "image":
            # already Anthropic-shaped (e.g. re-sent history); keep it
            blocks.append(b)
        # input_audio / file / unknown types: Claude cannot accept them -> skip
    return blocks


def _convert_openai_content_to_gemini_parts(content) -> list[dict]:
    """OpenAI content blocks -> Gemini parts.

    image_url -> inline_data (data URLs) or file_data (remote, best effort).
    input_audio -> inline_data with its audio mime type.
    """
    parts = []
    for b in _iter_content_blocks(content):
        btype = b.get("type", "text")
        if btype == "text":
            if b.get("text"):
                parts.append({"text": b.get("text", "")})
        elif btype == "image_url":
            url = (b.get("image_url") or {}).get("url", "")
            data = _parse_data_url(url)
            if data:
                parts.append({"inline_data": {"mime_type": data[0], "data": data[1]}})
            elif url.startswith("http"):
                parts.append({"file_data": {"file_uri": url, "mime_type": "image/*"}})
        elif btype == "input_audio":
            audio = b.get("input_audio") or {}
            fmt = audio.get("format", "wav")
            parts.append({"inline_data": {"mime_type": f"audio/{fmt}", "data": audio.get("data", "")}})
        # unknown types: skip
    return parts


def openai_to_claude(body: dict) -> tuple[dict, dict]:
    """Convert OpenAI chat completion request to Claude Messages API format."""
    messages = body.get("messages", [])
    system_parts = []
    claude_messages = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            blocks = _convert_openai_content_to_claude(content)
            system_parts.append("\n".join(b["text"] for b in blocks if b["type"] == "text"))
        elif role == "assistant":
            claude_messages.append({"role": "assistant", "content": content})
        else:
            claude_messages.append({"role": "user", "content": _convert_openai_content_to_claude(content)})

    claude_body = {
        "model": body.get("model", ""),
        "max_tokens": body.get("max_tokens", 4096),
        "messages": claude_messages,
    }
    if system_parts:
        claude_body["system"] = "\n".join(system_parts)
    if "temperature" in body:
        claude_body["temperature"] = body["temperature"]
    if "top_p" in body:
        claude_body["top_p"] = body["top_p"]
    if body.get("stream"):
        claude_body["stream"] = True

    return claude_body, {"anthropic-version": "2023-06-01", "content-type": "application/json"}


def openai_to_gemini(body: dict) -> tuple[dict, dict]:
    """Convert OpenAI chat completion request to Gemini GenerateContent format."""
    messages = body.get("messages", [])
    contents = []
    system_instruction = None

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            parts = _convert_openai_content_to_gemini_parts(content) or [{"text": ""}]
            system_instruction = {"parts": parts}
        elif role == "assistant":
            parts = _convert_openai_content_to_gemini_parts(content) or [{"text": ""}]
            contents.append({"role": "model", "parts": parts})
        else:
            parts = _convert_openai_content_to_gemini_parts(content) or [{"text": ""}]
            contents.append({"role": "user", "parts": parts})

    gemini_body = {"contents": contents}
    if system_instruction:
        gemini_body["systemInstruction"] = system_instruction

    gen_config = {}
    if "temperature" in body:
        gen_config["temperature"] = body["temperature"]
    if "max_tokens" in body:
        gen_config["maxOutputTokens"] = body["max_tokens"]
    if "top_p" in body:
        gen_config["topP"] = body["top_p"]
    if gen_config:
        gemini_body["generationConfig"] = gen_config

    return gemini_body, {"content-type": "application/json"}


def claude_stream_chunk_to_openai(chunk_data: dict, model: str, completion_id: str) -> dict | None:
    """Convert a Claude streaming event to OpenAI SSE chunk format."""
    event_type = chunk_data.get("type", "")

    if event_type == "content_block_delta":
        text = chunk_data.get("delta", {}).get("text", "")
        if text:
            return {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {"content": text},
                    "finish_reason": None,
                }],
            }

    elif event_type == "message_stop":
        return {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }],
        }

    return None


def gemini_stream_chunk_to_openai(chunk_data: dict, model: str, completion_id: str) -> dict | None:
    """Convert a Gemini streaming chunk to OpenAI SSE chunk format."""
    candidates = chunk_data.get("candidates", [])
    if not candidates:
        return None

    candidate = candidates[0]
    content = candidate.get("content", {})
    parts = content.get("parts", [])
    text = _gemini_parts_to_text(parts) if parts else ""
    finish_reason = candidate.get("finishReason")

    if text:
        return {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {"content": text},
                "finish_reason": None,
            }],
        }
    elif finish_reason:
        return {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }],
        }

    return None


def openai_response_to_openai(data: dict, model: str) -> dict:
    """Passthrough for OpenAI-protocol responses."""
    return data


def claude_response_to_openai(data: dict, model: str) -> dict:
    """Convert a complete Claude response to OpenAI format."""
    content = ""
    for block in data.get("content", []):
        if block.get("type") == "text":
            content += block.get("text", "")

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": data.get("usage", {}).get("input_tokens", 0),
            "completion_tokens": data.get("usage", {}).get("output_tokens", 0),
            "total_tokens": (
                data.get("usage", {}).get("input_tokens", 0)
                + data.get("usage", {}).get("output_tokens", 0)
            ),
        },
    }


def _gemini_parts_to_text(parts: list) -> str:
    """Flatten Gemini parts to text; inline images become markdown data-URI images."""
    chunks = []
    for p in parts:
        if p.get("text"):
            chunks.append(p["text"])
        inline = p.get("inline_data") or p.get("inlineData")
        if inline and inline.get("data"):
            mime = inline.get("mime_type") or inline.get("mimeType") or "image/png"
            chunks.append(f"![image](data:{mime};base64,{inline['data']})")
    return "".join(chunks)


def gemini_response_to_openai(data: dict, model: str) -> dict:
    """Convert a complete Gemini response to OpenAI format."""
    candidates = data.get("candidates", [])
    content = ""
    if candidates:
        parts = candidates[0].get("content", {}).get("parts", [])
        content = _gemini_parts_to_text(parts)

    usage = data.get("usageMetadata", {})
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": usage.get("promptTokenCount", 0),
            "completion_tokens": usage.get("candidatesTokenCount", 0),
            "total_tokens": usage.get("totalTokenCount", 0),
        },
    }

def openai_to_claude_response(data: dict) -> dict:
    "Convert an OpenAI-format completion response to Claude Messages API format."
    choices = data.get("choices", [])
    message = choices[0].get("message", {}) if choices else {}
    content_text = message.get("content", "")
    usage = data.get("usage", {})

    return {
        "id": data.get("id", ""),
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": content_text}],
        "model": data.get("model", ""),
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


def openai_to_gemini_response(data: dict) -> dict:
    "Convert an OpenAI-format completion response to Gemini GenerateContent format."
    choices = data.get("choices", [])
    message = choices[0].get("message", {}) if choices else {}
    content_text = message.get("content", "")
    usage = data.get("usage", {})
    finish_reason = choices[0].get("finish_reason", "stop") if choices else "stop"

    gemini_finish = "STOP"
    if finish_reason == "length":
        gemini_finish = "MAX_TOKENS"

    return {
        "candidates": [{
            "content": {"parts": [{"text": content_text}], "role": "model"},
            "finishReason": gemini_finish,
        }],
        "usageMetadata": {
            "promptTokenCount": usage.get("prompt_tokens", 0),
            "candidatesTokenCount": usage.get("completion_tokens", 0),
            "totalTokenCount": usage.get("total_tokens", 0),
        },
    }


def convert_openai_stream_to_claude_chunks(openai_chunk: dict, msg_id: str) -> str | None:
    "Convert an OpenAI SSE chunk to a Claude streaming event string."
    choices = openai_chunk.get("choices", [])
    if not choices:
        return None

    choice = choices[0]
    delta = choice.get("delta", {})
    finish = choice.get("finish_reason")
    content = delta.get("content", "")

    if content:
        event = {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": content},
        }
        return "event: content_block_delta\ndata: " + json.dumps(event, ensure_ascii=False) + "\n\n"

    if finish == "stop":
        event = {"type": "message_stop"}
        return "event: message_stop\ndata: " + json.dumps(event) + "\n\n"

    return None


def convert_openai_stream_to_gemini_chunks(openai_chunk: dict) -> str | None:
    "Convert an OpenAI SSE chunk to a Gemini streaming JSON line."
    choices = openai_chunk.get("choices", [])
    if not choices:
        return None

    choice = choices[0]
    delta = choice.get("delta", {})
    finish = choice.get("finish_reason")
    content = delta.get("content", "")

    if content:
        return json.dumps({
            "candidates": [{"content": {"parts": [{"text": content}], "role": "model"}}],
        }, ensure_ascii=False) + "\n"

    if finish == "stop":
        return json.dumps({
            "candidates": [{"content": {"parts": [], "role": "model"}, "finishReason": "STOP"}],
        }) + "\n"

    return None
# ============================================================
# Image Generation Protocol Adapters
# ============================================================

def openai_image_to_gemini(body: dict) -> dict:
    """Convert OpenAI /v1/images/generations request to Gemini generateContent format.

    For Gemini native image generation models (gemini-2.0-flash-preview-image-generation etc.),
    we use the generateContent endpoint with responseModalities including IMAGE.

    For Imagen models, we use the predict endpoint instead.
    Returns (gemini_body, endpoint_action) where endpoint_action is 'generateContent' or 'predict'.
    """
    model = body.get("model", "")
    prompt = body.get("prompt", "")

    if "imagen" in model.lower():
        # Imagen predict endpoint format
        imagen_body = {
            "instances": [{"prompt": prompt}],
            "parameters": {
                "sampleCount": body.get("n", 1),
            },
        }
        size = body.get("size", "1024x1024")
        if size and "x" in size:
            parts = size.split("x")
            try:
                imagen_body["parameters"]["width"] = int(parts[0])
                imagen_body["parameters"]["height"] = int(parts[1])
            except ValueError:
                pass
        return {"body": imagen_body, "action": "predict"}

    # Gemini native image generation via generateContent
    gemini_body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
        },
    }
    n = body.get("n", 1)
    if n and n > 1:
        gemini_body["generationConfig"]["candidateCount"] = min(n, 4)

    return {"body": gemini_body, "action": "generateContent"}


def gemini_image_response_to_openai(data: dict, model: str, prompt: str = "") -> dict:
    """Convert Gemini image generation response to OpenAI /v1/images/generations format."""
    created = int(time.time())
    image_data_list = []

    candidates = data.get("candidates", [])
    if candidates:
        parts = candidates[0].get("content", {}).get("parts", [])
        for part in parts:
            if "inlineData" in part:
                mime = part["inlineData"].get("mimeType", "image/png")
                b64 = part["inlineData"].get("data", "")
                image_data_list.append({
                    "b64_json": b64,
                    "revised_prompt": prompt,
                })
    elif "predictions" in data:
        for pred in data["predictions"]:
            b64 = pred.get("bytesBase64Encoded", "")
            if b64:
                image_data_list.append({
                    "b64_json": b64,
                    "revised_prompt": prompt,
                })

    return {
        "created": created,
        "data": image_data_list if image_data_list else [],
    }


def imagen_response_to_openai(data: dict, model: str) -> dict:
    """Convert Imagen predict response to OpenAI format."""
    return gemini_image_response_to_openai(data, model)


# ============================================================
# TTS / Audio Speech Protocol Adapters
# ============================================================

def openai_tts_to_gemini(body: dict) -> dict:
    """Convert OpenAI /v1/audio/speech request to Gemini generateContent format.

    Gemini TTS uses generateContent with speechConfig.
    """
    input_text = body.get("input", "")
    voice = body.get("voice", "Kore")

    gemini_body = {
        "contents": [{"role": "user", "parts": [{"text": input_text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {
                        "voiceName": voice,
                    }
                }
            },
        },
    }

    speed = body.get("speed")
    if speed:
        gemini_body["generationConfig"]["speechConfig"]["speakingRate"] = float(speed)

    return gemini_body


def gemini_tts_response_to_openai_audio(data: dict) -> bytes:
    """Extract raw audio bytes from Gemini TTS generateContent response."""
    candidates = data.get("candidates", [])
    if not candidates:
        return b""
    parts = candidates[0].get("content", {}).get("parts", [])
    for part in parts:
        if "inlineData" in part:
            import base64
            return base64.b64decode(part["inlineData"].get("data", ""))
    return b""


# ============================================================
# Video Generation Protocol Adapters
# ============================================================

def openai_video_request(body: dict) -> dict:
    """Normalize an OpenAI-style video generation request body.

    Different providers use different formats. This returns a unified dict
    that forwarder can dispatch.
    """
    return {
        "model": body.get("model", ""),
        "prompt": body.get("prompt", ""),
        "image": body.get("image") or body.get("init_image"),
        "images": body.get("images", []),
        "mode": body.get("mode", "ti2vid"),
        "n": body.get("n", 1),
        "size": body.get("size", "1152x768"),
        "num_frames": body.get("num_frames", 121),
        "frame_rate": body.get("frame_rate", 24),
        "seed": body.get("seed"),
        "negative_prompt": body.get("negative_prompt"),
        "extra_body": body.get("extra_body", {}),
    }


def video_request_to_gemini(body: dict) -> dict:
    """Convert normalized video request to Gemini Veo format.

    Note: Veo video generation is typically done via the Vertex AI /predict endpoint.
    This returns the body for that endpoint.
    """
    prompt = body.get("prompt", "")
    instances = [{"prompt": prompt}]

    image = body.get("image")
    if image:
        instances[0]["image"] = {"gcsUri": image} if image.startswith("gs://") else {"bytesBase64Encoded": ""}

    params = {}
    if body.get("num_frames"):
        params["sampleCount"] = body.get("n", 1)
    if body.get("seed") is not None:
        params["seed"] = body["seed"]

    return {"instances": instances, "parameters": params}


def video_response_to_openai(data: dict, task_id: str = "") -> dict:
    """Normalize video generation response to OpenAI-like format.

    Returns a dict with 'id', 'object', 'status', and optionally 'data' or 'video_url'.
    """
    # AgnesAi format
    if "task_id" in data or "id" in data:
        return {
            "id": data.get("task_id") or data.get("id") or task_id,
            "object": "video.generation",
            "status": data.get("status", "queued"),
            "video_url": data.get("video_url") or data.get("url", ""),
            "created": data.get("created", int(time.time())),
        }
    # Gemini Veo format (operation-based)
    if "name" in data:
        return {
            "id": data["name"].split("/")[-1] if "/" in data["name"] else data["name"],
            "object": "video.generation",
            "status": "in_progress" if not data.get("done") else "completed",
            "created": int(time.time()),
        }
    return {
        "id": task_id or f"vid-{uuid.uuid4().hex[:12]}",
        "object": "video.generation",
        "status": "unknown",
        "raw": data,
        "created": int(time.time()),
    }

# ============================================================
# OpenAI Responses API (Codex OAuth upstream) conversions
# ============================================================

def chat_to_responses_request(body: dict, model_id: str) -> dict:
    """Convert an OpenAI chat/completions body into a Codex Responses API request."""
    instructions = ""
    input_items = []
    for msg in body.get("messages", []):
        role = msg.get("role", "user")
        blocks = _iter_content_blocks(msg.get("content", ""))
        if role == "system":
            instructions += "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            continue
        content_items = []
        for b in blocks:
            if b.get("type") == "text":
                content_items.append({"type": "input_text", "text": b.get("text", "")})
            elif b.get("type") == "image_url":
                content_items.append({"type": "input_image", "image_url": (b.get("image_url") or {}).get("url", "")})
        if not content_items:
            continue
        input_items.append({"role": "assistant" if role == "assistant" else "user", "content": content_items})

    req = {
        "model": model_id,
        "instructions": instructions,
        "input": input_items,
        "stream": bool(body.get("stream")),
        "store": False,
    }
    if "temperature" in body:
        req["temperature"] = body["temperature"]
    if "top_p" in body:
        req["top_p"] = body["top_p"]
    return req


def responses_to_chat(data: dict, model_id: str) -> dict:
    """Convert a Responses API result into an OpenAI chat.completion response."""
    text = ""
    for out in data.get("output", []):
        if out.get("type") == "message":
            for c in out.get("content", []):
                if c.get("type") == "output_text":
                    text += c.get("text", "")
    usage = data.get("usage") or {}
    return {
        "id": data.get("id") or f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_id,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("total_tokens", usage.get("input_tokens", 0) + usage.get("output_tokens", 0)),
        },
    }


# ============================================================
# OpenAI Responses API (inbound) conversions
# 网关对外提供 POST /v1/responses：入站是 Responses 请求 / 响应，
# 内部统一走 chat.completions 链路，这里负责两个方向的转换。
# ============================================================

# 请求里需要「原样透传给上游 chat 端点」的标量字段
_RESPONSES_PASSTHROUGH = (
    "temperature", "top_p", "seed", "frequency_penalty", "presence_penalty",
    "stop", "user", "service_tier", "parallel_tool_calls",
)

_FINISH_REASON_TO_STATUS = {
    "stop": ("completed", None),
    "tool_calls": ("completed", None),
    "function_call": ("completed", None),
    "content_filter": ("incomplete", "content_filter"),
    "length": ("incomplete", "max_output_tokens"),
}


def _responses_text_of(content) -> str:
    """Flatten Responses input/instructions text content into plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") in ("input_text", "output_text", "text", "summary_text")
        )
    return ""


def _responses_content_to_openai(content) -> list[dict]:
    """Responses content parts -> OpenAI chat content blocks."""
    blocks = []
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if not isinstance(content, list):
        return []
    for b in content:
        if not isinstance(b, dict):
            continue
        btype = b.get("type", "")
        if btype in ("input_text", "output_text", "text", "summary_text"):
            blocks.append({"type": "text", "text": b.get("text", "")})
        elif btype == "input_image":
            url = b.get("image_url")
            if isinstance(url, dict):
                url = url.get("url")
            url = url or b.get("url") or b.get("file_id") or ""
            if url:
                image: dict = {"url": url}
                if b.get("detail"):
                    image["detail"] = b["detail"]
                blocks.append({"type": "image_url", "image_url": image})
        elif btype == "input_audio":
            audio = b.get("input_audio") if isinstance(b.get("input_audio"), dict) else b
            blocks.append({
                "type": "input_audio",
                "input_audio": {
                    "data": audio.get("data", ""),
                    "format": audio.get("format", "wav"),
                },
            })
        elif btype == "input_file":
            ref = b.get("file_id") or b.get("filename") or b.get("file_url") or ""
            if ref:
                blocks.append({"type": "text", "text": f"[file: {ref}]"})
        # unknown part types are dropped
    return blocks


def _responses_item_to_chat_messages(item) -> list[dict]:
    """One Responses input item -> zero or more chat messages."""
    if isinstance(item, str):
        return [{"role": "user", "content": item}] if item else []
    if not isinstance(item, dict):
        return []
    itype = item.get("type")
    if itype == "reasoning":
        # 无状态模式下 reasoning item 无实质内容，回传只会污染上下文
        return []
    if itype == "function_call":
        args = item.get("arguments") or ""
        if isinstance(args, (dict, list)):
            args = json.dumps(args, ensure_ascii=False)
        return [{"role": "assistant", "content": f"[tool_call] {item.get('name', '')} {args}".strip()}]
    if itype == "function_call_output":
        out = item.get("output", "")
        if not isinstance(out, str):
            out = json.dumps(out, ensure_ascii=False)
        return [{"role": "user", "content": f"[tool_result] {out}"}]
    role = item.get("role")
    content = item.get("content")
    if isinstance(content, str):
        return [{"role": role or "user", "content": content}] if content else []
    blocks = _responses_content_to_openai(content)
    if not blocks:
        return []
    return [{"role": role or "user", "content": blocks}]


def _responses_tools_to_chat(tools) -> list[dict]:
    """Responses tools -> chat.completions tools（内置工具无对应实现，丢弃）。"""
    out = []
    for t in tools or []:
        if not isinstance(t, dict) or t.get("type") != "function":
            continue
        if "function" in t:
            out.append(t)
            continue
        fn = {k: v for k, v in t.items() if k != "type"}
        if fn.get("name"):
            out.append({"type": "function", "function": fn})
    return out


def responses_request_to_chat(body: dict) -> dict:
    """Convert an inbound /v1/responses request into a chat/completions body.

    Deliberately stateless: `store` / `previous_response_id` are not honoured
    (the gateway keeps no response store), the caller owns the full history.
    """
    chat: dict = {"model": body.get("model", "")}
    messages: list[dict] = []

    instructions = body.get("instructions")
    instructions_text = _responses_text_of(instructions)
    if instructions_text.strip():
        messages.append({"role": "system", "content": instructions_text})

    raw_input = body.get("input")
    if isinstance(raw_input, str):
        if raw_input:
            messages.append({"role": "user", "content": raw_input})
    else:
        for item in raw_input or []:
            messages.extend(_responses_item_to_chat_messages(item))

    chat["messages"] = messages

    if body.get("stream"):
        chat["stream"] = True
    if body.get("max_output_tokens") is not None:
        chat["max_tokens"] = body["max_output_tokens"]
    for key in _RESPONSES_PASSTHROUGH:
        if body.get(key) is not None:
            chat[key] = body[key]

    tools = _responses_tools_to_chat(body.get("tools"))
    if tools:
        chat["tools"] = tools
    tool_choice = body.get("tool_choice")
    if tools and tool_choice is not None:
        chat["tool_choice"] = tool_choice

    reasoning = body.get("reasoning")
    if isinstance(reasoning, dict) and reasoning.get("effort"):
        chat["reasoning_effort"] = reasoning["effort"]

    text_cfg = body.get("text")
    if isinstance(text_cfg, dict) and isinstance(text_cfg.get("format"), dict):
        chat["response_format"] = text_cfg["format"]

    direct_provider_id = body.get("_direct_provider_id")
    if direct_provider_id is not None:
        chat["_direct_provider_id"] = direct_provider_id

    return chat


def _chat_usage_to_responses(usage: dict | None) -> dict | None:
    if not usage:
        return None
    input_tokens = usage.get("prompt_tokens", 0) or 0
    output_tokens = usage.get("completion_tokens", 0) or 0
    total = usage.get("total_tokens", 0) or (input_tokens + output_tokens)
    details_in = usage.get("prompt_tokens_details") or {}
    details_out = usage.get("completion_tokens_details") or {}
    return {
        "input_tokens": input_tokens,
        "input_tokens_details": {"cached_tokens": details_in.get("cached_tokens", 0) or 0},
        "output_tokens": output_tokens,
        "output_tokens_details": {"reasoning_tokens": details_out.get("reasoning_tokens", 0) or 0},
        "total_tokens": total,
    }


def _response_message_item(text: str, item_id: str, status: str = "completed") -> dict:
    return {
        "id": item_id,
        "type": "message",
        "status": status,
        "role": "assistant",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def _response_function_call_items(tool_calls) -> list[dict]:
    items = []
    for tc in tool_calls or []:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") or {}
        items.append({
            "id": f"fc_{uuid.uuid4().hex[:20]}",
            "type": "function_call",
            "status": "completed",
            "call_id": tc.get("id") or f"call_{uuid.uuid4().hex[:20]}",
            "name": fn.get("name", ""),
            "arguments": fn.get("arguments", "") or "",
        })
    return items


def response_envelope(
    response_id: str,
    model_id: str,
    status: str,
    output: list[dict],
    usage: dict | None = None,
    created_at: int | None = None,
    error: dict | None = None,
    incomplete_details: dict | None = None,
    instructions: str | None = None,
    max_output_tokens: int | None = None,
) -> dict:
    """Build a full OpenAI Response object."""
    return {
        "id": response_id,
        "object": "response",
        "created_at": created_at if created_at is not None else int(time.time()),
        "status": status,
        "error": error,
        "incomplete_details": incomplete_details,
        "instructions": instructions,
        "max_output_tokens": max_output_tokens,
        "model": model_id,
        "output": output,
        "parallel_tool_calls": True,
        "previous_response_id": None,
        "reasoning": {"effort": None, "summary": None},
        "store": False,
        "temperature": 1.0,
        "text": {"format": {"type": "text"}},
        "tool_choice": "auto",
        "tools": [],
        "top_p": 1.0,
        "truncation": "disabled",
        "usage": usage,
        "user": None,
        "metadata": {},
    }


def chat_completion_to_response(
    data: dict, model_id: str, response_id: str | None = None,
    instructions: str | None = None, max_output_tokens: int | None = None,
) -> dict:
    """Convert a chat.completion payload into a Responses API object."""
    choices = data.get("choices") or [{}]
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") or {}
    text = _responses_text_of(message.get("content"))
    finish_reason = choice.get("finish_reason")

    output: list[dict] = []
    if text:
        output.append(_response_message_item(text, f"msg_{uuid.uuid4().hex[:20]}"))
    output.extend(_response_function_call_items(message.get("tool_calls")))

    status, incomplete_reason = _FINISH_REASON_TO_STATUS.get(finish_reason or "stop", ("completed", None))
    incomplete_details = {"reason": incomplete_reason} if incomplete_reason else None

    return response_envelope(
        response_id=response_id or f"resp_{uuid.uuid4().hex[:24]}",
        model_id=model_id,
        status=status,
        output=output,
        usage=_chat_usage_to_responses(data.get("usage")),
        created_at=data.get("created") if isinstance(data.get("created"), int) else None,
        incomplete_details=incomplete_details,
        instructions=instructions,
        max_output_tokens=max_output_tokens,
    )


class ResponsesStreamWriter:
    """Incremental chat.completion.chunk -> Responses API SSE events.

    Chat chunks arrive as {"choices": [{"delta": {...}, "finish_reason": ...}]}.
    Each returned item is an (event_type, payload) pair to be written as
    `event: <type>` + `data: <payload>` (no `data: [DONE]` terminator).
    """

    def __init__(self, model_id: str, instructions: str | None = None,
                 max_output_tokens: int | None = None):
        self.model_id = model_id
        self.instructions = instructions
        self.max_output_tokens = max_output_tokens
        self.response_id = f"resp_{uuid.uuid4().hex[:24]}"
        self.item_id = f"msg_{uuid.uuid4().hex[:20]}"
        self.created_at = int(time.time())
        self.sequence = 0
        self.text = ""
        self.started = False
        self.finished = False
        self.finish_reason: str | None = None
        self.usage: dict | None = None
        self.error_payload: dict | None = None

    # -- internals ---------------------------------------------------------
    def _event(self, event_type: str, payload: dict) -> tuple[str, dict]:
        self.sequence += 1
        payload = {"type": event_type, "sequence_number": self.sequence, **payload}
        return event_type, payload

    def _item(self, status: str, text: str | None = None) -> dict:
        return _response_message_item(text if text is not None else self.text, self.item_id, status)

    # -- public API --------------------------------------------------------
    def _begin_events(self) -> list[tuple[str, dict]]:
        """Emit response.created / in_progress / output_item.added / content_part.added."""
        self.started = True
        empty = self._envelope("in_progress")
        return [
            self._event("response.created", {"response": empty}),
            self._event("response.in_progress", {"response": empty}),
            self._event("response.output_item.added", {
                "output_index": 0,
                "item": self._item("in_progress", text=""),
            }),
            self._event("response.content_part.added", {
                "item_id": self.item_id,
                "output_index": 0,
                "content_index": 0,
                "part": {"type": "output_text", "text": "", "annotations": []},
            }),
        ]

    def feed(self, chunk: dict) -> list[tuple[str, dict]]:
        if self.finished or not isinstance(chunk, dict):
            return []
        if chunk.get("model"):
            self.model_id = chunk["model"]
        if chunk.get("usage"):
            self.usage = chunk["usage"]

        upstream_error = chunk.get("error")
        if upstream_error:
            if isinstance(upstream_error, dict):
                message = upstream_error.get("message", "") or json.dumps(upstream_error, ensure_ascii=False)
                code = upstream_error.get("code") or upstream_error.get("type") or "server_error"
            else:
                message, code = str(upstream_error), "server_error"
            self.error_payload = {"code": code, "message": message}
            return self.fail(message)

        events: list[tuple[str, dict]] = []
        choices = chunk.get("choices") or []
        choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        delta = choice.get("delta") or {}
        text_delta = _responses_text_of(delta.get("content"))
        if choice.get("finish_reason"):
            self.finish_reason = choice["finish_reason"]

        if not self.started:
            events.extend(self._begin_events())

        if text_delta:
            self.text += text_delta
            events.append(self._event("response.output_text.delta", {
                "item_id": self.item_id,
                "output_index": 0,
                "content_index": 0,
                "delta": text_delta,
            }))

        return events

    def _envelope(self, status: str, output: list[dict] | None = None,
                  incomplete_details: dict | None = None) -> dict:
        return response_envelope(
            response_id=self.response_id,
            model_id=self.model_id,
            status=status,
            output=output or [],
            usage=_chat_usage_to_responses(self.usage) if status != "in_progress" else None,
            created_at=self.created_at,
            error=self.error_payload,
            incomplete_details=incomplete_details,
            instructions=self.instructions,
            max_output_tokens=self.max_output_tokens,
        )

    def _final_status(self) -> tuple[str, dict | None]:
        status, incomplete_reason = _FINISH_REASON_TO_STATUS.get(
            self.finish_reason or "stop", ("completed", None)
        )
        if self.error_payload:
            return "failed", None
        return status, ({"reason": incomplete_reason} if incomplete_reason else None)

    def _final_response(self) -> dict:
        status, incomplete_details = self._final_status()
        return self._envelope(status, [self._item("completed")] if self.text else [], incomplete_details)

    def finish(self) -> list[tuple[str, dict]]:
        if self.finished:
            return []
        self.finished = True
        events: list[tuple[str, dict]] = []
        if not self.started:
            events.extend(self._begin_events())
        if self.text:
            events.append(self._event("response.output_text.done", {
                "item_id": self.item_id,
                "output_index": 0,
                "content_index": 0,
                "text": self.text,
            }))
        events.append(self._event("response.content_part.done", {
            "item_id": self.item_id,
            "output_index": 0,
            "content_index": 0,
            "part": {"type": "output_text", "text": self.text, "annotations": []},
        }))
        events.append(self._event("response.output_item.done", {
            "output_index": 0,
            "item": self._item("completed"),
        }))
        events.append(self._event("response.completed", {"response": self._final_response()}))
        return events

    def fail(self, message: str) -> list[tuple[str, dict]]:
        if not self.error_payload:
            self.error_payload = {"code": "server_error", "message": message}
        self.finished = True
        events: list[tuple[str, dict]] = []
        if not self.started:
            events.extend(self._begin_events())
        events.append(self._event("error", {
            "code": (self.error_payload or {}).get("code", "server_error"),
            "message": message,
            "param": None,
        }))
        events.append(self._event("response.failed", {"response": self._final_response()}))
        return events


def responses_stream_chunk_to_chat(chunk_data: dict, model_id: str, completion_id: str) -> dict | None:
    """Convert one Responses API SSE event into an OpenAI chat chunk (or None)."""
    event_type = chunk_data.get("type", "")
    if event_type == "response.output_text.delta":
        return {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model_id,
            "choices": [{"index": 0, "delta": {"content": chunk_data.get("delta", "")}, "finish_reason": None}],
        }
    if event_type == "response.completed":
        return {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model_id,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
    return None


# ============================================================
# Inbound client-format endpoints (POST /v1/messages,
# POST /v1beta/models/{model}:generateContent) -> chat body.
# Responses (inbound) -> openai_to_claude_response / openai_to_gemini_response.
# ============================================================

def _claude_content_to_openai(content) -> list[dict]:
    """Claude Messages content (string or block list) -> OpenAI content blocks."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    blocks = []
    for b in content or []:
        if not isinstance(b, dict):
            continue
        btype = b.get("type", "")
        if btype == "text":
            blocks.append({"type": "text", "text": b.get("text", "")})
        elif btype == "image":
            source = b.get("source") or {}
            if source.get("type") == "base64":
                media = source.get("media_type", "image/png")
                blocks.append({"type": "image_url", "image_url": {
                    "url": f"data:{media};base64,{source.get('data', '')}"}})
            elif source.get("url"):
                blocks.append({"type": "image_url", "image_url": {"url": source["url"]}})
        elif btype == "tool_use":
            blocks.append({"type": "text", "text": json.dumps(
                {"tool_call": b.get("name", ""), "input": b.get("input", {})}, ensure_ascii=False)})
        elif btype == "tool_result":
            inner = b.get("content", "")
            if not isinstance(inner, str):
                inner = "\n".join(
                    c.get("text", "") for c in (inner or []) if isinstance(c, dict))
            blocks.append({"type": "text", "text": f"[tool_result] {inner}"})
        # thinking / redacted_thinking blocks are dropped (not usable upstream)
    return blocks


def _claude_tools_to_chat(tools) -> list[dict]:
    out = []
    for t in tools or []:
        if not isinstance(t, dict) or not t.get("name"):
            continue
        out.append({"type": "function", "function": {
            "name": t.get("name", ""),
            "description": t.get("description", ""),
            "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
        }})
    return out


def _claude_tool_choice_to_chat(tool_choice):
    if isinstance(tool_choice, str):
        return tool_choice
    if isinstance(tool_choice, dict):
        ttype = tool_choice.get("type", "auto")
        if ttype == "auto":
            return "auto"
        if ttype == "any":
            return "required"
        if ttype == "tool" and tool_choice.get("name"):
            return {"type": "function", "function": {"name": tool_choice["name"]}}
        if ttype == "none":
            return "none"
    return "auto"


def claude_request_to_chat(body: dict) -> dict:
    """Convert an Anthropic /v1/messages request into a chat/completions body."""
    chat: dict = {"model": body.get("model", "")}
    messages: list[dict] = []

    system = body.get("system")
    if isinstance(system, str):
        if system:
            messages.append({"role": "system", "content": system})
    elif isinstance(system, list):
        text = "\n".join(
            b.get("text", "") for b in system if isinstance(b, dict) and b.get("type") == "text")
        if text:
            messages.append({"role": "system", "content": text})

    for msg in body.get("messages", []):
        role = msg.get("role", "user")
        if role not in ("user", "assistant"):
            role = "user"
        blocks = _claude_content_to_openai(msg.get("content", ""))
        if blocks:
            messages.append({"role": role, "content": blocks})

    chat["messages"] = messages
    for src, dst in (("max_tokens", "max_tokens"), ("temperature", "temperature"),
                     ("top_p", "top_p"), ("top_k", "top_k")):
        if body.get(src) is not None:
            chat[dst] = body[src]
    if body.get("stop_sequences"):
        chat["stop"] = body["stop_sequences"]
    if body.get("stream"):
        chat["stream"] = True

    tools = _claude_tools_to_chat(body.get("tools"))
    if tools:
        chat["tools"] = tools
    if body.get("tool_choice") is not None:
        chat["tool_choice"] = _claude_tool_choice_to_chat(body.get("tool_choice"))
    return chat


def _gemini_parts_to_openai(parts) -> list[dict]:
    """Gemini parts -> OpenAI content blocks."""
    blocks = []
    for p in parts or []:
        if not isinstance(p, dict):
            continue
        if p.get("text"):
            blocks.append({"type": "text", "text": p["text"]})
        inline = p.get("inlineData") or p.get("inline_data")
        if inline:
            mime = inline.get("mimeType") or inline.get("mime_type") or "application/octet-stream"
            data = inline.get("data", "")
            if mime.startswith("audio/"):
                blocks.append({"type": "input_audio",
                               "input_audio": {"data": data, "format": mime.split("/", 1)[1]}})
            else:
                blocks.append({"type": "image_url",
                               "image_url": {"url": f"data:{mime};base64,{data}"}})
        file_ref = p.get("fileData") or p.get("file_data")
        if file_ref:
            uri = file_ref.get("fileUri") or file_ref.get("file_uri") or ""
            if uri:
                blocks.append({"type": "image_url", "image_url": {"url": uri}})
    return blocks


def _gemini_tools_to_chat(tools) -> list[dict]:
    out = []
    for t in tools or []:
        if not isinstance(t, dict):
            continue
        for fd in t.get("functionDeclarations") or t.get("function_declarations") or []:
            if not fd.get("name"):
                continue
            out.append({"type": "function", "function": {
                "name": fd.get("name", ""),
                "description": fd.get("description", ""),
                "parameters": fd.get("parameters") or {"type": "object", "properties": {}},
            }})
    return out


def gemini_request_to_chat(body: dict, model: str) -> dict:
    """Convert a Gemini GenerateContent request into a chat/completions body.

    `model` comes from the URL path (`/v1beta/models/{model}:generateContent`).
    """
    chat: dict = {"model": model}
    messages: list[dict] = []

    system_instruction = body.get("systemInstruction") or body.get("system_instruction")
    if system_instruction:
        parts = _gemini_parts_to_openai(system_instruction.get("parts"))
        if parts:
            messages.append({"role": "system", "content": parts})

    for content in body.get("contents", []):
        role = content.get("role", "user")
        parts = _gemini_parts_to_openai(content.get("parts"))
        if not parts:
            continue
        messages.append({"role": "model" if role == "model" else "user", "content": parts})

    chat["messages"] = messages

    gen = body.get("generationConfig") or body.get("generation_config") or {}
    for src, dst in (("temperature", "temperature"), ("topP", "top_p"),
                     ("topK", "top_k"), ("maxOutputTokens", "max_tokens"),
                     ("stopSequences", "stop")):
        if gen.get(src) is not None:
            chat[dst] = gen[src]

    tools = _gemini_tools_to_chat(body.get("tools"))
    if tools:
        chat["tools"] = tools
    tool_config = body.get("toolConfig") or body.get("tool_config") or {}
    fcc = tool_config.get("functionCallingConfig") or tool_config.get("function_calling_config") or {}
    mode = fcc.get("mode")
    if mode == "ANY":
        chat["tool_choice"] = "required"
    elif mode == "NONE":
        chat["tool_choice"] = "none"
    elif mode == "AUTO":
        chat["tool_choice"] = "auto"
    return chat

