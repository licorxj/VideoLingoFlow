"""统一的 json / text 输入解析工具。

让所有 json / text 类型输入端口兼容两种来源：
- 内存中的真实数据（dict / list / 内联 JSON 字符串 / 文本字符串）
- 文件路径（绝对路径，或相对任务目录 task_dir 的路径，指向 .json / .txt 等文件）

所有「数据类」节点（字幕、ASR、文案、配音、合并、封面、剪辑项目、贴片坐标、
水印、音乐上游参数等）都应通过该模块解析输入，从而同时支持上游直接传数据
与上游传文件路径两种情况。
"""
import os
import json


def resolve_json_input(value, task_dir: str = ""):
    """把 json 输入解析为 Python 对象（dict / list）。

    - dict / list：直接返回（内存数据）
    - str 且指向已存在的文件（绝对路径，或相对 task_dir）：读取并 json.load
    - str 且为合法 JSON 文本：json.loads
    - 其它：抛出 ValueError
    """
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            raise ValueError(f"无法识别的 JSON 输入类型：{type(value).__name__}")
        return value
    v = value.strip()
    if not v:
        raise ValueError("JSON 输入为空")

    # 文件路径优先（绝对路径或相对任务目录）
    if os.path.isabs(v) and os.path.isfile(v):
        with open(v, "r", encoding="utf-8") as f:
            return json.load(f)
    if task_dir:
        rel = os.path.join(task_dir, v)
        if os.path.isfile(rel):
            with open(rel, "r", encoding="utf-8") as f:
                return json.load(f)

    # 否则当作内联 JSON 文本
    try:
        return json.loads(v)
    except json.JSONDecodeError:
        raise ValueError(f"JSON 输入既不是有效文件路径，也不是合法 JSON 文本：{v[:80]}")


def resolve_project_json(value, task_dir: str = ""):
    """解析剪辑项目 JSON：兼容内存 dict / list、文件路径。

    返回解析后的数据；未提供或无法解析时返回 None（交由节点回退到仓库当前状态）。
    """
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    v = value.strip()
    candidates = []
    if os.path.isabs(v) and os.path.isfile(v):
        candidates.append(v)
    if task_dir:
        rel = os.path.join(task_dir, v)
        if os.path.isfile(rel):
            candidates.append(rel)
    if candidates:
        with open(candidates[0], "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def resolve_text_input(value, task_dir: str = ""):
    """把 text 输入解析为字符串内容。

    - str 且指向已存在的文件（绝对路径，或相对 task_dir）：读取文本内容
    - 其它 str：原样返回（内存文本）
    - None：返回空串；其它类型：转字符串
    """
    if isinstance(value, str):
        candidate = value.strip()
        if candidate:
            if os.path.isabs(candidate) and os.path.isfile(candidate):
                with open(candidate, "r", encoding="utf-8") as f:
                    return f.read()
            if task_dir:
                rel = os.path.join(task_dir, candidate)
                if os.path.isfile(rel):
                    with open(rel, "r", encoding="utf-8") as f:
                        return f.read()
        return value
    if value is None:
        return ""
    return str(value)
