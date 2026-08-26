"""qmhub - Capabilities API (能力列表/详情)"""


class CapabilitiesAPI:
    def __init__(self, client):
        self._client = client

    def list(self) -> list:
        """列出所有已公开且启用的能力。"""
        return self._client._request("GET", "/api/capability/capabilities") or []

    def get(self, slug: str) -> dict:
        """获取指定能力的详情。"""
        return self._client._request("GET", f"/api/capability/capabilities/{slug}")
