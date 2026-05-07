"""Contract tests for Graphiti Zep-like adapter without external deps."""

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Minimal package scaffolding
app_pkg = types.ModuleType("app")
app_pkg.__path__ = [str(ROOT / "app")]
sys.modules.setdefault("app", app_pkg)
utils_pkg = types.ModuleType("app.utils")
utils_pkg.__path__ = [str(ROOT / "app" / "utils")]
sys.modules.setdefault("app.utils", utils_pkg)

config_mod = types.ModuleType("app.config")


class Config:
    GRAPHITI_BASE_URL = "http://localhost:8000/"
    GRAPHITI_TIMEOUT_SECONDS = 60
    GRAPHITI_INGEST_TIMEOUT_SECONDS = 180
    GRAPHITI_TRUST_ENV = False


config_mod.Config = Config
sys.modules["app.config"] = config_mod

# httpx stub that captures constructor args and requests
httpx_mod = types.ModuleType("httpx")


class DummyResponse:
    def __init__(self, payload, content=True, *, status_error=False, text=""):
        self._payload = payload
        self.content = b"1" if content else b""
        self.text = text
        self.status_error = status_error

    def raise_for_status(self):
        if self.status_error:
            raise DummyHTTPStatusError("boom", request={"path": "x"}, response=self)
        return None

    def json(self):
        return self._payload


class DummyHTTPStatusError(Exception):
    def __init__(self, message, request=None, response=None):
        super().__init__(message)
        self.request = request
        self.response = response


class DummyClient:
    init_kwargs = None
    requests = []
    closed = False

    def __init__(self, **kwargs):
        DummyClient.init_kwargs = kwargs

    def request(self, method, path, **kwargs):
        DummyClient.requests.append((method, path, kwargs))
        if path == "/v1/groups":
            return DummyResponse({"uuid_": "g-1", "meta": {"owner": {"id": "u1"}}})
        if path.endswith("/ontology"):
            return DummyResponse({"ok": True})
        if path.endswith("/episodes:batch"):
            return DummyResponse([{"uuid_": "ep-1"}, {"uuid_": "ep-2"}])
        if path.endswith("/search"):
            return DummyResponse({"facts": [{"fact": "a->b"}]})
        if path == "/v1/threads":
            if method == "GET":
                return DummyResponse({"threads": [{"thread_id": "t-1"}], "next_page_token": None})
            return DummyResponse({"thread_id": "t-new"})
        if path.startswith("/v1/threads/"):
            return DummyResponse({"thread_id": path.rsplit('/', 1)[-1]})
        if path.startswith("/v1/nodes/"):
            return DummyResponse({"uuid_": "n-1"})
        if path.startswith("/v1/edges/"):
            return DummyResponse({"uuid_": "e-1"})
        if path.startswith("/v1/episodes/"):
            return DummyResponse({"uuid_": "ep-1", "processed": True})
        if path.startswith("/v1/groups/") and "/episodes" in path:
            return DummyResponse([{"uuid_": "ep-1", "source_description": "chunk_id=abc", "processed": True}])
        if path.startswith("/v1/groups/") and "/nodes" in path:
            return DummyResponse([{"uuid_": "n-1"}])
        if path.startswith("/v1/groups/") and "/edges" in path:
            return DummyResponse([{"uuid_": "e-1"}])
        return DummyResponse({"ok": True})

    def close(self):
        DummyClient.closed = True


httpx_mod.Client = DummyClient
httpx_mod.HTTPStatusError = DummyHTTPStatusError
sys.modules["httpx"] = httpx_mod

spec = importlib.util.spec_from_file_location("app.utils.graph_client", ROOT / "app" / "utils" / "graph_client.py")
mod = importlib.util.module_from_spec(spec)
sys.modules["app.utils.graph_client"] = mod
spec.loader.exec_module(mod)

# Construct client, verify base config passed to httpx client
client = mod.create_graphiti_client("k1")
assert DummyClient.init_kwargs["base_url"] == "http://localhost:8000"
assert DummyClient.init_kwargs["headers"]["Authorization"] == "Bearer k1"

# Graph API checks
created = client.graph.create("g-1", "name", "desc")
assert created.uuid_ == "g-1"
assert created.meta.owner.id == "u1"

client.graph.set_ontology(["g-1", "g-2"], entities={"A": {}}, edges={"R": {}})
ontology_calls = [c for c in DummyClient.requests if c[1].endswith("/ontology")]
assert len(ontology_calls) == 2

episodes = [mod.EpisodeData(data="x"), mod.EpisodeData(data="y", type="note", source_description="chunk_id=abc")]
added = client.graph.add_batch("g-1", episodes)
assert added[0].uuid_ == "ep-1"
add_call = [c for c in DummyClient.requests if c[1].endswith("/episodes:batch")][-1]
assert add_call[2]["json"]["episodes"][1]["type"] == "note"
assert add_call[2]["json"]["episodes"][1]["source_description"] == "chunk_id=abc"
assert "source_description" not in add_call[2]["json"]["episodes"][0]
assert add_call[2]["timeout"] == 180

episodes_by_graph = client.graph.episode.get_by_graph_id("g-1", limit=10)
assert episodes_by_graph[0].source_description == "chunk_id=abc"
episode_list_call = [c for c in DummyClient.requests if c[1] == "/v1/groups/g-1/episodes"][-1]
assert episode_list_call[2]["params"] == {"limit": 10}

search = client.graph.search(graph_id="g-1", query="alice")
assert search.facts[0].fact == "a->b"
search_call = [c for c in DummyClient.requests if c[1].endswith("/search")][-1]
assert search_call[1] == "/v1/groups/g-1/search"
assert search_call[2]["json"]["query"] == "alice"

# Thread API checks
threads = client.thread.get_threads(user_id="u-1", limit=5, page_token="p1")
assert threads.threads[0].thread_id == "t-1"
threads_call = [c for c in DummyClient.requests if c[1] == "/v1/threads" and c[0] == "GET"][-1]
assert threads_call[2]["params"] == {"limit": 5, "user_id": "u-1", "page_token": "p1"}

created_thread = client.thread.create(thread_id="t-custom", user_id="u-1", metadata={"k": "v"})
assert created_thread.thread_id == "t-new"
create_thread_call = [c for c in DummyClient.requests if c[1] == "/v1/threads" and c[0] == "POST"][-1]
assert create_thread_call[2]["json"]["thread_id"] == "t-custom"

single_thread = client.thread.get("t-123")
assert single_thread.thread_id == "t-123"

client.thread.delete("t-123")
assert DummyClient.requests[-1][0] == "DELETE"
assert DummyClient.requests[-1][1] == "/v1/threads/t-123"

# Error body is preserved in raised status errors
failing_http = mod._GraphitiHTTP("k1")
failing_http._client = types.SimpleNamespace(
    request=lambda *args, **kwargs: DummyResponse(
        {"detail": "bad upstream"},
        status_error=True,
        text='{"detail":"bad upstream"}',
    )
)
try:
    failing_http.request("POST", "/v1/fail")
    raise AssertionError("expected HTTP status error")
except DummyHTTPStatusError as exc:
    assert 'Response body: {"detail":"bad upstream"}' in str(exc)

# low-level resource closing
client.close()
assert DummyClient.closed is True

print("ok")
