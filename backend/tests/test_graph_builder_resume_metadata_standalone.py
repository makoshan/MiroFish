"""Standalone regression checks for graph build resume metadata helpers."""

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
httpx_mod.HTTPStatusError = Exception
sys.modules["httpx"] = httpx_mod

spec = importlib.util.spec_from_file_location(
    "app.services.graph_builder",
    ROOT / "app" / "services" / "graph_builder.py",
)
mod = importlib.util.module_from_spec(spec)
sys.modules["app.services.graph_builder"] = mod
spec.loader.exec_module(mod)

text_hash = mod.GraphBuilderService.compute_text_hash("hello")
assert len(text_hash) == 64
assert text_hash == mod.GraphBuilderService.compute_text_hash("hello")
assert text_hash != mod.GraphBuilderService.compute_text_hash("hello!")

checkpoint = {
    "graph_id": "g-1",
    "text_hash": text_hash,
    "chunk_size": 400,
    "chunk_overlap": 40,
    "total_chunks": 4,
    "last_completed_chunk_index": 2,
}
assert mod.GraphBuilderService.get_resume_start_index(
    checkpoint,
    graph_id="g-1",
    text_hash=text_hash,
    chunk_size=400,
    chunk_overlap=40,
    total_chunks=4,
) == 3
assert mod.GraphBuilderService.get_resume_start_index(
    checkpoint,
    graph_id="g-2",
    text_hash=text_hash,
    chunk_size=400,
    chunk_overlap=40,
    total_chunks=4,
) == 0
assert mod.GraphBuilderService.get_resume_start_index(
    checkpoint,
    graph_id="g-1",
    text_hash="changed",
    chunk_size=400,
    chunk_overlap=40,
    total_chunks=4,
) == 0

source = mod.GraphBuilderService.build_chunk_source_description(
    project_id="proj-1",
    text_hash=text_hash,
    chunk_index=2,
    total_chunks=4,
    chunk="hello chunk",
)
assert "mirofish" in source
assert "project=proj-1" in source
assert "chunk=2/4" in source
assert f"text_hash={text_hash[:16]}" in source
assert "chunk_id=" in source

print("ok")
