"""creation 模块内部公共工具。"""

from datetime import datetime


class CreationDataError(RuntimeError):
    pass


class NotFoundError(CreationDataError):
    pass


class ValidationError(CreationDataError):
    pass


def row_to_dict(row) -> dict:
    """把 SQLAlchemy 行转为可 JSON 化的 dict(datetime 转 ISO 字符串)。

    注意：列名 ``metadata`` 与 SQLAlchemy 声明基类的类属性冲突，实例上实际
    映射属性是 ``metadata_json``（见 models.py 的 mapped_column("metadata")），
    直接 ``getattr(row, "metadata")`` 会拿到类级 MetaData 对象而非列值，这里做别名兜底。
    """
    data = {}
    for column in type(row).__table__.columns:
        name = column.name
        attr = "metadata_json" if name == "metadata" and hasattr(row, "metadata_json") else name
        value = getattr(row, attr)
        data[name] = value.isoformat() if isinstance(value, datetime) else value
    return data


def ensure_tag_list(value) -> list[str]:
    """标签字段归一化:None→[], 字符串→逗号切分, 其余→list。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(tag).strip() for tag in value if str(tag).strip()]
