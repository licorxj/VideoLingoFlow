import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.control_plane.assets import AssetDescriptor, AssetStore
from backend.control_plane.models import Checkpoint


def config_hash(config: dict) -> str:
    return hashlib.sha256(json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def record_checkpoint(session: Session, node_id: str, checkpoint_key: str, input_hash: str, step_version: str, node_config: dict, descriptor: AssetDescriptor, store: AssetStore) -> Checkpoint:
    if not store.verify(descriptor):
        raise ValueError("检查点对象校验和不一致")
    item = session.scalar(select(Checkpoint).where(Checkpoint.node_id == node_id, Checkpoint.checkpoint_key == checkpoint_key))
    values = {"input_hash": input_hash, "step_version": step_version, "config_hash": config_hash(node_config), "output_object_key": descriptor.object_key, "output_checksum": descriptor.content_sha256, "payload": {"kind": descriptor.kind, "size_bytes": descriptor.size_bytes, "content_type": descriptor.content_type}}
    if item is None:
        item = Checkpoint(node_id=node_id, checkpoint_key=checkpoint_key, **values)
        session.add(item)
    else:
        for key, value in values.items():
            setattr(item, key, value)
        item.version += 1
    session.flush()
    return item


def reusable_checkpoint(session: Session, node_id: str, checkpoint_key: str, input_hash: str, step_version: str, node_config: dict, store: AssetStore) -> Checkpoint | None:
    item = session.scalar(select(Checkpoint).where(Checkpoint.node_id == node_id, Checkpoint.checkpoint_key == checkpoint_key, Checkpoint.input_hash == input_hash, Checkpoint.step_version == step_version, Checkpoint.config_hash == config_hash(node_config)))
    if item is None or not item.output_object_key or not item.output_checksum:
        return None
    descriptor = AssetDescriptor(item.node.task.project_id, item.payload.get("kind", "checkpoint"), item.output_object_key, item.output_checksum, item.payload.get("size_bytes", 0), item.payload.get("content_type", "application/octet-stream"))
    if not store.verify(descriptor):
        return None
    return item
