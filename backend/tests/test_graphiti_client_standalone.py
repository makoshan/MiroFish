import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

app_pkg = types.ModuleType("app")
app_pkg.__path__ = [str(ROOT / "app")]
sys.modules.setdefault("app", app_pkg)
utils_pkg = types.ModuleType("app.utils")
utils_pkg.__path__ = [str(ROOT / "app" / "utils")]
sys.modules.setdefault("app.utils", utils_pkg)

config_mod = types.ModuleType("app.config")


class Config:
    GRAPHITI_BASE_URL = "http://localhost:8000"
    GRAPHITI_TIMEOUT_SECONDS = 60
    GRAPHITI_TRUST_ENV = False


config_mod.Config = Config
sys.modules["app.config"] = config_mod

httpx_mod = types.ModuleType("httpx")


class DummyClient:
    def __init__(self, *args, **kwargs):
        pass

    def request(self, *args, **kwargs):
        raise RuntimeError("not used")

    def close(self):
        return None


httpx_mod.Client = DummyClient
sys.modules["httpx"] = httpx_mod

spec_gc = importlib.util.spec_from_file_location(
    "app.utils.graph_client", ROOT / "app" / "utils" / "graph_client.py"
)
mod_gc = importlib.util.module_from_spec(spec_gc)
sys.modules["app.utils.graph_client"] = mod_gc
spec_gc.loader.exec_module(mod_gc)

EpisodeData = mod_gc.EpisodeData
GraphOps = mod_gc._GraphOps
ThreadOps = mod_gc._ThreadOps


class FakeHTTP:
    def __init__(self):
        self.calls = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if path.endswith('/episodes:batch'):
            return [{"uuid_": "ep-1"}]
        if path.endswith('/nodes'):
            return [{"uuid_": "n1", "name": "Alice"}]
        if path == '/v1/threads':
            return {"threads": [{"thread_id": "t-1"}], "next_page_token": None}
        return {"ok": True}


http = FakeHTTP()
ops = GraphOps(http)
result = ops.add_batch("g1", [EpisodeData(data="hello")])
assert result[0].uuid_ == "ep-1"
assert http.calls[0][1] == "/v1/groups/g1/episodes:batch"

nodes = ops.node.get_by_graph_id("g1")
assert nodes[0].name == "Alice"

thread_ops = ThreadOps(http)
threads = thread_ops.get_threads(user_id="u-1", limit=5)
assert threads.threads[0].thread_id == "t-1"
assert http.calls[-1][1] == "/v1/threads"
assert http.calls[-1][2]["params"]["user_id"] == "u-1"
assert http.calls[-1][2]["params"]["limit"] == 5

print("ok")
