"""Standalone retry test for graph batch ingestion rate limits."""

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

app_pkg = types.ModuleType("app")
app_pkg.__path__ = [str(ROOT / "app")]
sys.modules.setdefault("app", app_pkg)

services_pkg = types.ModuleType("app.services")
services_pkg.__path__ = [str(ROOT / "app" / "services")]
sys.modules.setdefault("app.services", services_pkg)

utils_pkg = types.ModuleType("app.utils")
utils_pkg.__path__ = [str(ROOT / "app" / "utils")]
sys.modules.setdefault("app.utils", utils_pkg)

models_pkg = types.ModuleType("app.models")
models_pkg.__path__ = [str(ROOT / "app" / "models")]
sys.modules.setdefault("app.models", models_pkg)

config_mod = types.ModuleType("app.config")


class Config:
    GRAPHITI_API_KEY = "k1"


config_mod.Config = Config
sys.modules["app.config"] = config_mod

graph_client_mod = types.ModuleType("app.utils.graph_client")


class EpisodeData:
    def __init__(self, data: str, type: str = "text"):
        self.data = data
        self.type = type


graph_client_mod.EpisodeData = EpisodeData
sys.modules["app.utils.graph_client"] = graph_client_mod

task_mod = types.ModuleType("app.models.task")
task_mod.TaskManager = object
task_mod.TaskStatus = object
sys.modules["app.models.task"] = task_mod

zep_paging_mod = types.ModuleType("app.utils.zep_paging")
zep_paging_mod.fetch_all_nodes = lambda *args, **kwargs: []
zep_paging_mod.fetch_all_edges = lambda *args, **kwargs: []
sys.modules["app.utils.zep_paging"] = zep_paging_mod

zep_client_mod = types.ModuleType("app.utils.zep_client")
zep_client_mod.create_zep_client = lambda *args, **kwargs: None
sys.modules["app.utils.zep_client"] = zep_client_mod

text_processor_mod = types.ModuleType("app.services.text_processor")
text_processor_mod.TextProcessor = object
sys.modules["app.services.text_processor"] = text_processor_mod

httpx_mod = types.ModuleType("httpx")


class HTTPStatusError(Exception):
    def __init__(self, message: str, request=None, response=None):
        super().__init__(message)
        self.request = request
        self.response = response


httpx_mod.HTTPStatusError = HTTPStatusError
sys.modules["httpx"] = httpx_mod

spec = importlib.util.spec_from_file_location(
    "app.services.graph_builder",
    ROOT / "app" / "services" / "graph_builder.py",
)
mod = importlib.util.module_from_spec(spec)
sys.modules["app.services.graph_builder"] = mod
spec.loader.exec_module(mod)


class FakeGraph:
    def __init__(self):
        self.calls = 0

    def add_batch(self, graph_id, episodes):
        self.calls += 1
        if self.calls == 1:
            response = types.SimpleNamespace(status_code=429)
            raise HTTPStatusError(
                "too many requests. Response body: rate limit exceeded",
                request={"path": f"/v1/groups/{graph_id}/episodes:batch"},
                response=response,
            )
        return [types.SimpleNamespace(uuid_="ep-1")]


class TimeoutGraph:
    def __init__(self):
        self.calls = 0

    def add_batch(self, graph_id, episodes):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("504 Gateway Timeout from upstream")
        return [types.SimpleNamespace(uuid_="ep-timeout")]


class SlowGraph:
    def __init__(self):
        self.calls = 0

    def add_batch(self, graph_id, episodes):
        self.calls += 1
        return [types.SimpleNamespace(uuid_="ep-slow")]


service = mod.GraphBuilderService.__new__(mod.GraphBuilderService)
service.client = types.SimpleNamespace(graph=FakeGraph())

sleep_calls = []
mod.time.sleep = lambda seconds: sleep_calls.append(seconds)

messages = []
result = service.add_text_batches(
    graph_id="g-1",
    chunks=["hello world"],
    batch_size=1,
    progress_callback=lambda message, progress: messages.append((message, progress)),
)

assert result == ["ep-1"]
assert service.client.graph.calls == 2
assert sleep_calls == [15]
assert any("超时或限流" in message for message, _ in messages)

sleep_calls.clear()
messages.clear()

timeout_service = mod.GraphBuilderService.__new__(mod.GraphBuilderService)
timeout_service.client = types.SimpleNamespace(graph=TimeoutGraph())
timeout_result = timeout_service.add_text_batches(
    graph_id="g-2",
    chunks=["hello again"],
    batch_size=1,
    progress_callback=lambda message, progress: messages.append((message, progress)),
)

assert timeout_result == ["ep-timeout"]
assert timeout_service.client.graph.calls == 2
assert 15 in sleep_calls
assert any("超时或限流" in message for message, _ in messages)

messages.clear()


class FakeFuture:
    def __init__(self):
        self.calls = 0

    def result(self, timeout=None):
        self.calls += 1
        if self.calls == 1:
            raise mod.concurrent.futures.TimeoutError()
        return [types.SimpleNamespace(uuid_="ep-slow")]


class FakeExecutor:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def submit(self, fn, **kwargs):
        return FakeFuture()


mod.concurrent.futures.ThreadPoolExecutor = lambda max_workers=1: FakeExecutor()

slow_service = mod.GraphBuilderService.__new__(mod.GraphBuilderService)
slow_service.client = types.SimpleNamespace(graph=SlowGraph())
slow_result = slow_service.add_text_batches(
    graph_id="g-3",
    chunks=["slow chunk"],
    batch_size=1,
    progress_callback=lambda message, progress: messages.append((message, progress)),
)

assert slow_result == ["ep-slow"]
assert any("处理中，已等待" in message for message, _ in messages)

print("ok")
