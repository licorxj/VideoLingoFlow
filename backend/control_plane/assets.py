import hashlib
import mimetypes
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO, Iterator, Protocol
from urllib.parse import quote

from backend.control_plane.models import Asset


class AssetError(RuntimeError):
    pass


class AssetIntegrityError(AssetError):
    pass


class AssetAccessError(AssetError):
    pass


@dataclass(frozen=True)
class AssetDescriptor:
    project_id: str
    kind: str
    object_key: str
    content_sha256: str
    size_bytes: int
    content_type: str


class AssetStore(Protocol):
    def put(self, stream: BinaryIO, descriptor: AssetDescriptor, metadata: dict | None = None) -> AssetDescriptor: ...

    def stream(self, descriptor: AssetDescriptor, chunk_size: int = 1024 * 1024) -> Iterator[bytes]: ...

    def remove(self, descriptor: AssetDescriptor, protected: bool = False) -> None: ...

    def verify(self, descriptor: AssetDescriptor) -> bool: ...

    def presigned_download(self, descriptor: AssetDescriptor, expires_seconds: int = 300) -> str: ...


_PROJECT_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[a-fA-F0-9]{64}$")
_KINDS = {"project", "task", "node-cache", "checkpoint", "export", "temporary"}
_RETENTION_DAYS = {"temporary": 1, "node-cache": 7, "task": 30, "export": 30}


def asset_object_key(project_id: str, kind: str, name: str) -> str:
    if not _PROJECT_KEY.fullmatch(project_id) or kind not in _KINDS:
        raise AssetAccessError("非法资产范围")
    candidate = Path(name)
    if candidate.is_absolute() or candidate.drive:
        raise AssetAccessError("非法对象键")
    clean_name = "/".join(part for part in candidate.parts if part not in ("", "."))
    if not clean_name or clean_name.startswith("..") or ".." in clean_name.split("/"):
        raise AssetAccessError("非法对象键")
    return f"projects/{project_id}/{kind}/{clean_name}"


def default_expiry(kind: str) -> datetime | None:
    days = _RETENTION_DAYS.get(kind)
    return datetime.now(timezone.utc) + timedelta(days=days) if days else None


def sha256_stream(stream: BinaryIO, chunk_size: int = 1024 * 1024) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(chunk_size):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def sha256_file(path: Path) -> tuple[str, int]:
    with path.open("rb") as stream:
        return sha256_stream(stream)


def local_asset_root() -> Path:
    configured = os.getenv("CONTROL_PLANE_ASSET_ROOT")
    if configured:
        return Path(configured).expanduser()
    data_root = os.getenv("CONTROL_PLANE_DATA_ROOT")
    if data_root:
        return Path(data_root).expanduser() / "assets"
    return Path(__file__).resolve().parents[2] / "data" / "assets"


def _check_descriptor_scope(descriptor: AssetDescriptor) -> None:
    if not _PROJECT_KEY.fullmatch(descriptor.project_id) or descriptor.kind not in _KINDS:
        raise AssetAccessError("资产不属于项目范围")
    prefix = f"projects/{descriptor.project_id}/{descriptor.kind}/"
    if not descriptor.object_key.startswith(prefix):
        raise AssetAccessError("资产不属于项目范围")
    name = descriptor.object_key.removeprefix(prefix)
    if asset_object_key(descriptor.project_id, descriptor.kind, name) != descriptor.object_key:
        raise AssetAccessError("资产不属于项目范围")
    if not _SHA256.fullmatch(descriptor.content_sha256) or descriptor.size_bytes < 0:
        raise AssetIntegrityError("资产描述符校验失败")


class MinioAssetStore:
    def __init__(self, client=None, bucket: str | None = None):
        self.bucket = bucket or os.getenv("MINIO_BUCKET", "videolingo-assets")
        self.client = client or self._build_client()

    def _build_client(self):
        from minio import Minio

        endpoint = os.getenv("MINIO_ENDPOINT", "127.0.0.1:9000")
        return Minio(endpoint, access_key=os.environ["MINIO_ROOT_USER"], secret_key=os.environ["MINIO_ROOT_PASSWORD"], secure=os.getenv("MINIO_SECURE", "0") == "1")

    def ensure_bucket(self) -> None:
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def put(self, stream: BinaryIO, descriptor: AssetDescriptor, metadata: dict | None = None) -> AssetDescriptor:
        digest, size = sha256_stream(stream)
        if digest != descriptor.content_sha256 or size != descriptor.size_bytes:
            raise AssetIntegrityError("上传内容校验失败")
        stream.seek(0)
        self.ensure_bucket()
        self.client.put_object(self.bucket, descriptor.object_key, stream, size, content_type=descriptor.content_type, metadata={"x-amz-meta-sha256": digest, **(metadata or {})}, part_size=10 * 1024 * 1024)
        return descriptor

    def put_file(self, path: Path, project_id: str, kind: str, name: str, content_type: str | None = None) -> AssetDescriptor:
        digest, size = sha256_file(path)
        descriptor = AssetDescriptor(project_id, kind, asset_object_key(project_id, kind, name), digest, size, content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        with path.open("rb") as stream:
            return self.put(stream, descriptor)

    def presigned_upload(self, project_id: str, kind: str, name: str, expires_seconds: int = 300) -> dict:
        key = asset_object_key(project_id, kind, name)
        return {"object_key": key, "url": self.client.presigned_put_object(self.bucket, key, expires=timedelta(seconds=expires_seconds)), "expires_seconds": expires_seconds}

    def presigned_download(self, descriptor: AssetDescriptor, expires_seconds: int = 300) -> str:
        self._check_scope(descriptor)
        return self.client.presigned_get_object(self.bucket, descriptor.object_key, expires=timedelta(seconds=expires_seconds))

    def stream(self, descriptor: AssetDescriptor, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        self._check_scope(descriptor)
        response = self.client.get_object(self.bucket, descriptor.object_key)
        try:
            while chunk := response.read(chunk_size):
                yield chunk
        finally:
            response.close()
            response.release_conn()

    def verify(self, descriptor: AssetDescriptor) -> bool:
        self._check_scope(descriptor)
        stat = self.client.stat_object(self.bucket, descriptor.object_key)
        return _object_checksum(stat) == descriptor.content_sha256

    def remove(self, descriptor: AssetDescriptor, protected: bool = False) -> None:
        self._check_scope(descriptor)
        if protected:
            raise AssetAccessError("受保护资产不可清理")
        self.client.remove_object(self.bucket, descriptor.object_key)

    @staticmethod
    def _check_scope(descriptor: AssetDescriptor) -> None:
        _check_descriptor_scope(descriptor)


class LocalAssetStore:
    def __init__(self, root: Path | str | None = None):
        self.root = Path(root).expanduser().resolve() if root is not None else local_asset_root().resolve()

    def put(self, stream: BinaryIO, descriptor: AssetDescriptor, metadata: dict | None = None) -> AssetDescriptor:
        target = self._path_for(descriptor)
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(prefix=".asset-", dir=target.parent)
        temporary = Path(temporary_name)
        try:
            digest = hashlib.sha256()
            size = 0
            with os.fdopen(handle, "wb") as output:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if digest.hexdigest() != descriptor.content_sha256 or size != descriptor.size_bytes:
                raise AssetIntegrityError("上传内容校验失败")
            os.replace(temporary, target)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return descriptor

    def put_file(self, path: Path, project_id: str, kind: str, name: str, content_type: str | None = None) -> AssetDescriptor:
        digest, size = sha256_file(path)
        descriptor = AssetDescriptor(project_id, kind, asset_object_key(project_id, kind, name), digest, size, content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        with path.open("rb") as stream:
            return self.put(stream, descriptor)

    def presigned_upload(self, project_id: str, kind: str, name: str, expires_seconds: int = 300) -> dict:
        key = asset_object_key(project_id, kind, name)
        raise AssetAccessError("本地文件存储不支持预签名上传 URL")

    def presigned_download(self, descriptor: AssetDescriptor, expires_seconds: int = 300) -> str:
        self._path_for(descriptor)
        raise AssetAccessError("本地文件存储不支持预签名下载 URL，请使用下载接口")

    def stream(self, descriptor: AssetDescriptor, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        path = self._path_for(descriptor)
        with path.open("rb") as stream:
            while chunk := stream.read(chunk_size):
                yield chunk

    def verify(self, descriptor: AssetDescriptor) -> bool:
        path = self._path_for(descriptor)
        if not path.is_file():
            return False
        digest, size = sha256_file(path)
        return digest == descriptor.content_sha256 and size == descriptor.size_bytes

    def remove(self, descriptor: AssetDescriptor, protected: bool = False) -> None:
        if protected:
            raise AssetAccessError("受保护资产不可清理")
        self._path_for(descriptor).unlink(missing_ok=True)

    def _path_for(self, descriptor: AssetDescriptor) -> Path:
        _check_descriptor_scope(descriptor)
        relative = Path(*(quote(part, safe="-_.()") for part in descriptor.object_key.split("/")))
        path = (self.root / relative).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise AssetAccessError("资产路径超出本地存储根目录") from exc
        return path


def _object_checksum(stat) -> str | None:
    metadata = getattr(stat, "metadata", {}) or {}
    return metadata.get("x-amz-meta-sha256") or metadata.get("X-Amz-Meta-Sha256")


def asset_record(descriptor: AssetDescriptor, task_id: str | None = None, expires_at=None) -> Asset:
    return Asset(project_id=descriptor.project_id, task_id=task_id, kind=descriptor.kind, object_key=descriptor.object_key, content_sha256=descriptor.content_sha256, size_bytes=descriptor.size_bytes, content_type=descriptor.content_type, expires_at=expires_at or default_expiry(descriptor.kind))
