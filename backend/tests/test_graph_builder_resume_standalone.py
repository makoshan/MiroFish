"""Standalone regression checks for resumable graph chunk ingestion."""

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
    GRAPHITI_API_KEY = "***"


config_mod.Config = Config
sys.modules["app.config"] = config_mod

graph_client_mod = types.ModuleType("app.utils.graph_client")


class EpisodeData:
    def __init__(self, data: str, type: str = "text", source_description: str | None = None):
        self.data = data
        self.type = type
        self.source_description = source_description


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


class CapturingGraph:
    def __init__(self):
        self.calls = []

    def add_batch(self, graph_id, episodes):
        self.calls.append((graph_id, episodes[0]))
        return [types.SimpleNamespace(uuid_=f"ep-{len(self.calls)}")]


service = mod.GraphBuilderService.__new__(mod.GraphBuilderService)
service.client = types.SimpleNamespace(graph=CapturingGraph())

checkpoints = []
messages = []
result = service.add_text_batches(
    graph_id="g-resume",
    chunks=["chunk-0", "chunk-1", "chunk-2", "chunk-3"],
    batch_size=2,
    start_index=2,
    source_description_factory=lambda idx, total, chunk: f"chunk={idx}/{total} data={chunk}",
    checkpoint_callback=lambda idx, ep_uuid: checkpoints.append((idx, ep_uuid)),
    progress_callback=lambda message, progress: messages.append((message, progress)),
)

assert result == ["ep-1", "ep-2"]
assert [episode.data for _, episode in service.client.graph.calls] == ["chunk-2", "chunk-3"]
assert [episode.source_description for _, episode in service.client.graph.calls] == [
    "chunk=2/4 data=chunk-2",
    "chunk=3/4 data=chunk-3",
]
assert checkpoints == [(2, "ep-1"), (3, "ep-2")]
assert any("从第 3/4 块继续" in message for message, _ in messages)
assert any("已完成 4/4 块" in message for message, _ in messages)

print("ok")
