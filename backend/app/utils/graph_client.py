"""Graphiti client adapter with a Zep-like API surface.

The goal of this module is to keep MiroFish service code stable while
routing requests to a Graphiti server (typically backed by Neo4j in
self-hosted deployments).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import httpx

from ..config import Config


@dataclass
class EpisodeData:
    data: str
    type: str = "text"


@dataclass
class EntityEdgeSourceTarget:
    source: str
    target: str


def _to_obj(value: Any) -> Any:
    if isinstance(value, dict):
        return SimpleNamespace(**{k: _to_obj(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_to_obj(v) for v in value]
    return value


class _GraphitiHTTP:
    def __init__(self, api_key: str):
        self._client = httpx.Client(
            base_url=Config.GRAPHITI_BASE_URL.rstrip("/"),
            timeout=Config.GRAPHITI_TIMEOUT_SECONDS,
            trust_env=Config.GRAPHITI_TRUST_ENV,
            follow_redirects=True,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        if "timeout" not in kwargs and path.endswith("/episodes:batch"):
            kwargs["timeout"] = Config.GRAPHITI_INGEST_TIMEOUT_SECONDS
        resp = self._client.request(method, path, **kwargs)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip() if exc.response is not None else ""
            if detail:
                message = f"{exc}. Response body: {detail[:500]}"
                raise httpx.HTTPStatusError(message, request=exc.request, response=exc.response) from exc
            raise
        if not resp.content:
            return None
        return resp.json()

    def close(self):
        self._client.close()


class _EpisodeOps:
    def __init__(self, http: _GraphitiHTTP):
        self._http = http

    def get(self, uuid_: str):
        return _to_obj(self._http.request("GET", f"/v1/episodes/{uuid_}"))


class _NodeOps:
    def __init__(self, http: _GraphitiHTTP):
        self._http = http

    def get_by_graph_id(self, graph_id: str, limit: int = 100, uuid_cursor: str | None = None):
        params = {"limit": limit}
        if uuid_cursor:
            params["uuid_cursor"] = uuid_cursor
        data = self._http.request("GET", f"/v1/groups/{graph_id}/nodes", params=params) or []
        return [_to_obj(item) for item in data]

    def get_entity_edges(self, node_uuid: str):
        data = self._http.request("GET", f"/v1/nodes/{node_uuid}/edges") or []
        return [_to_obj(item) for item in data]

    def get(self, uuid_: str):
        return _to_obj(self._http.request("GET", f"/v1/nodes/{uuid_}"))


class _EdgeOps:
    def __init__(self, http: _GraphitiHTTP):
        self._http = http

    def get_by_graph_id(self, graph_id: str, limit: int = 100, uuid_cursor: str | None = None):
        params = {"limit": limit}
        if uuid_cursor:
            params["uuid_cursor"] = uuid_cursor
        data = self._http.request("GET", f"/v1/groups/{graph_id}/edges", params=params) or []
        return [_to_obj(item) for item in data]

    def get(self, uuid_: str):
        return _to_obj(self._http.request("GET", f"/v1/edges/{uuid_}"))


class _GraphOps:
    def __init__(self, http: _GraphitiHTTP):
        self._http = http
        self.node = _NodeOps(http)
        self.edge = _EdgeOps(http)
        self.episode = _EpisodeOps(http)

    def create(self, graph_id: str, name: str, description: str):
        return _to_obj(
            self._http.request(
                "POST",
                "/v1/groups",
                json={"group_id": graph_id, "name": name, "description": description},
            )
        )

    def set_ontology(
        self,
        graph_ids: list[str],
        entities: dict[str, Any] | None = None,
        edges: dict[str, Any] | None = None,
    ):
        for gid in graph_ids:
            self._http.request(
                "POST",
                f"/v1/groups/{gid}/ontology",
                json={"entities": entities or {}, "edges": edges or {}},
            )

    def add_batch(self, graph_id: str, episodes: list[EpisodeData]):
        payload = [{"content": ep.data, "type": ep.type} for ep in episodes]
        data = self._http.request(
            "POST",
            f"/v1/groups/{graph_id}/episodes:batch",
            json={"episodes": payload},
        ) or []
        return [_to_obj(item) for item in data]

    def search(self, **kwargs: Any):
        graph_id = kwargs.pop("graph_id")
        return _to_obj(self._http.request("POST", f"/v1/groups/{graph_id}/search", json=kwargs))

    def delete(self, graph_id: str):
        return self._http.request("DELETE", f"/v1/groups/{graph_id}")


class _ThreadOps:
    """Zep-like Thread API backed by Graphiti thread endpoints."""

    def __init__(self, http: _GraphitiHTTP):
        self._http = http

    def get_threads(
        self,
        *,
        user_id: str | None = None,
        limit: int = 20,
        page_token: str | None = None,
    ):
        params: dict[str, Any] = {"limit": limit}
        if user_id:
            params["user_id"] = user_id
        if page_token:
            params["page_token"] = page_token
        return _to_obj(self._http.request("GET", "/v1/threads", params=params))

    def get(self, thread_id: str):
        return _to_obj(self._http.request("GET", f"/v1/threads/{thread_id}"))

    def create(self, *, thread_id: str | None = None, user_id: str | None = None, metadata: dict[str, Any] | None = None):
        payload: dict[str, Any] = {}
        if thread_id:
            payload["thread_id"] = thread_id
        if user_id:
            payload["user_id"] = user_id
        if metadata:
            payload["metadata"] = metadata
        return _to_obj(self._http.request("POST", "/v1/threads", json=payload))

    def delete(self, thread_id: str):
        return self._http.request("DELETE", f"/v1/threads/{thread_id}")


class GraphitiClient:
    def __init__(self, api_key: str):
        self._http = _GraphitiHTTP(api_key)
        self.graph = _GraphOps(self._http)
        self.thread = _ThreadOps(self._http)

    def close(self):
        self._http.close()


def create_graphiti_client(api_key: str) -> GraphitiClient:
    return GraphitiClient(api_key)
