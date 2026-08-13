"""
Protocol adapter: converts OpenAI-format requests to upstream provider formats
and converts streaming responses back to OpenAI format.
"""
import json
import uuid
import time


def openai_to_claude(body: dict) -> tuple[dict, dict]:
    """Convert OpenAI chat completion request to Claude Messages API format."""
    messages = body.get("messages", [])
    system_parts = []
    claude_messages = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            system_parts.append(content)
        elif role == "assistant":
            claude_messages.append({"role": "assistant", "content": content})
        else:
            claude_messages.append({"role": "user", "content": content})

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
            system_instruction = {"parts": [{"text": content}]}
        elif role == "assistant":
            contents.append({"role": "model", "parts": [{"text": content}]})
        else:
            contents.append({"role": "user", "parts": [{"text": content}]})

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
    text = "".join(p.get("text", "") for p in parts) if parts else ""
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


def gemini_response_to_openai(data: dict, model: str) -> dict:
    """Convert a complete Gemini response to OpenAI format."""
    candidates = data.get("candidates", [])
    content = ""
    if candidates:
        parts = candidates[0].get("content", {}).get("parts", [])
        content = "".join(p.get("text", "") for p in parts)

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