from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


NODE_TYPES_DIR = Path(__file__).parent.parent / "config" / "node_types"


def load_custom_node_definition(node_type: str) -> dict | None:
    path = NODE_TYPES_DIR / f"{node_type}.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def run_custom_node(node_type: str, node_id: str, definition: dict, node_config: dict, step_inputs: dict, workspace: Path, timeout: int) -> dict:
    exec_type = str(definition.get("execType") or "").lower()
    cache_dir = workspace / "cache"
    cache_dir.mkdir(exist_ok=True)
    if not exec_type:
        return {"outputs": dict(step_inputs), "artifacts": []}
    command = str(definition.get("execCode") or "")
    code_dir = Path(str(definition.get("codeDir") or ""))
    exec_file = str(definition.get("execFile") or "")
    if exec_type == "python" and not command:
        if not exec_file:
            raise ValueError("自定义 Python 节点缺少内联代码或入口文件")
        script_path = Path(exec_file)
        if not script_path.is_absolute():
            script_path = code_dir / script_path if code_dir else script_path
        if not script_path.exists():
            raise ValueError(f"自定义 Python 入口文件不存在: {script_path}")
        process_command: list[str] | str = [sys.executable, str(script_path)]
        use_shell = False
    elif exec_type == "python":
        with tempfile.NamedTemporaryFile("w", suffix=".py", prefix=f"custom_{node_id}_", dir=cache_dir, encoding="utf-8", delete=False) as file:
            file.write(
                "import json\n"
                "import os\n"
                "task_dir = os.environ['TASK_DIR']\n"
                "cache_dir = os.environ['CACHE_DIR']\n"
                "node_id = os.environ['NODE_ID']\n"
                "node_config = json.loads(os.environ['NODE_CONFIG_JSON'])\n"
                "step_inputs = json.loads(os.environ['STEP_INPUTS_JSON'])\n"
                "config = node_config\n"
                "inputs = step_inputs\n"
                "produced = {}\n"
                + command
                + "\nwith open(os.environ['OUTPUTS_JSON_PATH'], 'w', encoding='utf-8') as _outputs_file:\n    json.dump(produced, _outputs_file, ensure_ascii=False)\n"
            )
            script_path = Path(file.name)
        process_command = [sys.executable, str(script_path)]
        use_shell = False
    elif exec_type == "shell":
        if not command:
            raise ValueError("自定义 Shell 节点缺少命令")
        process_command = command
        use_shell = True
        script_path = None
    elif exec_type == "llm":
        from backend.config import settings
        from openai import OpenAI
        import httpx

        prompt = command
        for key, value in {**step_inputs, **node_config}.items():
            prompt = prompt.replace("{" + str(key) + "}", str(value))
        response = OpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_API_BASE,
            http_client=httpx.Client(timeout=max(1, timeout), trust_env=False),
        ).chat.completions.create(
            model=node_config.get("model", settings.SMALL_MODEL),
            messages=[{"role": "user", "content": prompt}],
            temperature=node_config.get("temperature", 0.7),
        )
        output_path = workspace / "cache" / f"{node_id}_llm_output.txt"
        output_path.write_text(response.choices[0].message.content or "", encoding="utf-8")
        return {"outputs": {"text": str(output_path)}, "artifacts": [str(output_path)]}
    else:
        raise ValueError(f"不支持的自定义节点执行类型: {exec_type}")

    outputs_path = cache_dir / f"{node_id}_outputs.json"
    env = os.environ.copy()
    env.update({"TASK_DIR": str(workspace), "CACHE_DIR": str(cache_dir), "NODE_ID": node_id, "OUTPUTS_JSON_PATH": str(outputs_path)})
    env["NODE_CONFIG_JSON"] = json.dumps(node_config, ensure_ascii=False)
    env["STEP_INPUTS_JSON"] = json.dumps(step_inputs, ensure_ascii=False)
    env.update({f"INPUT_{str(key).upper()}": str(value) for key, value in step_inputs.items()})
    env.update({f"CONFIG_{str(key).upper()}": str(value) for key, value in node_config.items()})
    try:
        result = subprocess.run(process_command, shell=use_shell, cwd=workspace, env=env, capture_output=True, text=True, timeout=max(1, timeout), encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired as error:
        raise TimeoutError(f"自定义节点超时: {timeout}s") from error
    finally:
        if exec_type == "python" and command and script_path:
            script_path.unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "自定义节点执行失败")[-1000:])
    outputs: dict = {}
    if outputs_path.exists():
        try:
            outputs = json.loads(outputs_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            outputs = {}
    if not isinstance(outputs, dict):
        raise ValueError("OUTPUTS_JSON_PATH 必须写入 JSON 对象")
    artifacts = [str(path) for path in cache_dir.glob(f"{node_id}_*") if path != outputs_path]
    return {"outputs": outputs, "artifacts": artifacts, "stdout": (result.stdout or "")[-1000:]}
