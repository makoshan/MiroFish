"""Standalone regression checks for persisted graph build checkpoints."""

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

app_pkg = types.ModuleType("app")
app_pkg.__path__ = [str(ROOT / "app")]
sys.modules.setdefault("app", app_pkg)

models_pkg = types.ModuleType("app.models")
models_pkg.__path__ = [str(ROOT / "app" / "models")]
sys.modules.setdefault("app.models", models_pkg)

config_mod = types.ModuleType("app.config")


class Config:
    UPLOAD_FOLDER = str(ROOT / "uploads")


config_mod.Config = Config
sys.modules["app.config"] = config_mod

spec = importlib.util.spec_from_file_location(
    "app.models.project",
    ROOT / "app" / "models" / "project.py",
)
mod = importlib.util.module_from_spec(spec)
sys.modules["app.models.project"] = mod
spec.loader.exec_module(mod)

project = mod.Project(
    project_id="proj-resume",
    name="Resume Project",
    status=mod.ProjectStatus.GRAPH_BUILDING,
    created_at="2026-01-01T00:00:00",
    updated_at="2026-01-01T00:00:00",
    graph_build_checkpoint={
        "graph_id": "g-1",
        "text_hash": "abc",
        "chunk_size": 400,
        "chunk_overlap": 40,
        "total_chunks": 4,
        "last_completed_chunk_index": 2,
        "completed_episode_uuids": ["ep-0", "ep-1", "ep-2"],
        "status": "ingesting",
    },
)

data = project.to_dict()
assert data["graph_build_checkpoint"]["last_completed_chunk_index"] == 2
assert data["graph_build_checkpoint"]["completed_episode_uuids"] == ["ep-0", "ep-1", "ep-2"]

restored = mod.Project.from_dict(data)
assert restored.graph_build_checkpoint["graph_id"] == "g-1"
assert restored.graph_build_checkpoint["text_hash"] == "abc"
assert restored.graph_build_checkpoint["total_chunks"] == 4

legacy = mod.Project.from_dict({
    "project_id": "legacy",
    "name": "Legacy",
    "status": "failed",
    "created_at": "",
    "updated_at": "",
})
assert legacy.graph_build_checkpoint is None

print("ok")
