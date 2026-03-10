from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from anthropic import AsyncAnthropic
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, Field, create_model
from pydantic_settings import BaseSettings, SettingsConfigDict

from graphiti_core import Graphiti
from graphiti_core.cross_encoder.client import CrossEncoderClient
from graphiti_core.embedder import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.edges import EntityEdge
from graphiti_core.llm_client import LLMConfig, OpenAIClient
from graphiti_core.llm_client.anthropic_client import AnthropicClient
from graphiti_core.llm_client.errors import RateLimitError as GraphitiRateLimitError
from graphiti_core.nodes import EntityNode, EpisodicNode

logger = logging.getLogger(__name__)


def _resolve_schema_refs(schema: dict) -> dict:
    """Inline all $ref/$defs so providers that don't support $ref can use the schema."""
    defs = schema.get("$defs", {})

    def resolve(obj: Any) -> Any:
        if isinstance(obj, dict):
            if "$ref" in obj:
                ref_name = obj["$ref"].split("/")[-1]
                return resolve(defs.get(ref_name, obj))
            return {k: resolve(v) for k, v in obj.items() if k != "$defs"}
        if isinstance(obj, list):
            return [resolve(item) for item in obj]
        return obj

    return resolve(schema)


_PRIMITIVE_TYPES = {"string", "integer", "number", "boolean"}


def _schema_expects_primitive(schema: dict) -> bool:
    """Check if a JSON schema field expects a primitive type (including nullable)."""
    if not schema:
        return True  # No schema info — assume primitive to be safe for Neo4j
    t = schema.get("type", "")
    if t in _PRIMITIVE_TYPES:
        return True
    # Handle anyOf/oneOf (e.g. str | None → {"anyOf": [{"type": "string"}, {"type": "null"}]})
    for combo_key in ("anyOf", "oneOf"):
        variants = schema.get(combo_key, [])
        if variants and all(
            v.get("type") in _PRIMITIVE_TYPES or v.get("type") == "null"
            for v in variants
        ):
            return True
    return False


def _flatten_value(v: Any) -> Any:
    """Convert nested dicts/list-of-dicts to JSON strings for Neo4j compatibility."""
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list) and v and isinstance(v[0], dict):
        return json.dumps(v, ensure_ascii=False)
    return v


def _fix_field_names(data: Any, schema: dict) -> Any:
    """Recursively fix field names in data to match the expected JSON schema.

    Also flattens complex nested values to JSON strings when the schema
    expects primitive types (Neo4j only supports primitives as property values).
    """
    if isinstance(data, dict):
        props = schema.get("properties", {})
        if not props:
            return data
        expected_keys = set(props.keys())
        actual_keys = set(data.keys())
        missing = expected_keys - actual_keys
        extra = actual_keys - expected_keys
        # Try to map extra keys to missing keys
        renames: dict[str, str] = {}
        # First pass: suffix/substring matching
        unmatched_missing = set(missing)
        unmatched_extra = set(extra)
        for m in list(unmatched_missing):
            for e in list(unmatched_extra):
                if e.endswith(f"_{m}") or e.endswith(m) or m in e or e in m:
                    renames[e] = m
                    unmatched_missing.discard(m)
                    unmatched_extra.discard(e)
                    break
        # Second pass: if exactly one missing and one extra, force rename
        # (common with LLMs using synonyms like "nodes" for "extracted_entities")
        if len(unmatched_missing) == 1 and len(unmatched_extra) == 1:
            e = next(iter(unmatched_extra))
            m = next(iter(unmatched_missing))
            # Only if the value type roughly matches the schema type
            e_val = data.get(e)
            m_schema = props.get(m, {})
            if (m_schema.get("type") == "array" and isinstance(e_val, (list, str))) or \
               (m_schema.get("type") != "array"):
                renames[e] = m
        result = {}
        for k, v in data.items():
            new_key = renames.get(k, k)
            child_schema = props.get(new_key, {})
            child_type = child_schema.get("type", "")
            if child_type == "array" and isinstance(v, list):
                item_schema = child_schema.get("items", {})
                if item_schema.get("type") == "object" or item_schema.get("properties"):
                    v = [_fix_field_names(item, item_schema) for item in v]
                else:
                    # Array of primitives - flatten any complex items
                    v = [_flatten_value(item) if isinstance(item, (dict, list)) else item for item in v]
            elif child_type == "object" or (isinstance(v, dict) and child_schema.get("properties")):
                v = _fix_field_names(v, child_schema)
            elif isinstance(v, (dict, list)) and _schema_expects_primitive(child_schema):
                # Schema expects a primitive but got a complex value — flatten
                v = _flatten_value(v)
            result[new_key] = v
        return result
    if isinstance(data, list):
        items_schema = schema.get("items", {})
        return [_fix_field_names(item, items_schema) for item in data]
    return data


def _unwrap_structured_payload(data: Any, schema: dict) -> Any:
    """Unwrap provider-specific wrapper objects around the actual JSON payload."""
    if not isinstance(data, dict):
        return data

    expected_keys = set((schema.get("properties") or {}).keys())
    if not expected_keys:
        return data

    current = data
    seen: set[int] = set()
    wrapper_keys = ("properties", "arguments", "result", "data", "value")

    while isinstance(current, dict) and id(current) not in seen:
        seen.add(id(current))
        if expected_keys & set(current.keys()):
            return current

        nested = None
        for key in wrapper_keys:
            inner = current.get(key)
            if isinstance(inner, dict):
                nested = inner
                break

        if nested is None and len(current) == 1:
            only_value = next(iter(current.values()))
            if isinstance(only_value, dict):
                nested = only_value

        if nested is None:
            return current
        current = nested

    return current


class ChatCompletionsClient(OpenAIClient):
    """OpenAI-compatible client using chat.completions for structured outputs.

    Replaces the default Responses API (`/v1/responses`) with
    `/v1/chat/completions` + function calling, so any OpenAI-compatible
    provider (Moonshot, Qwen, etc.) works with graphiti-core.
    """

    def __init__(self, config=None, cache=False, client=None, **kwargs):
        super().__init__(config, cache, client, **kwargs)
        if config is None:
            from graphiti_core.llm_client.config import LLMConfig
            config = LLMConfig()
        # Override with a client that has a longer timeout (default is too short for entity extraction)
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=300.0,
        )

    async def _create_structured_completion(
        self,
        model: str,
        messages: list[ChatCompletionMessageParam],
        temperature: float | None,
        max_tokens: int,
        response_model: type[BaseModel],
        reasoning: str | None = None,
        verbosity: str | None = None,
    ) -> Any:
        fn_name = response_model.__name__
        parameters = _resolve_schema_refs(response_model.model_json_schema())

        # The messages already contain the JSON schema from graphiti-core's
        # generate_response().  We just need to ensure the model outputs valid
        # JSON conforming to the exact field names in that schema.
        #
        # Strategy: use response_format=json_object so the model MUST return
        # JSON, and prepend a system nudge about using exact field names.
        enhanced_messages = list(messages)
        # Insert a system-level reminder as the second message (after the main system prompt)
        enhanced_messages.insert(1, {
            "role": "system",
            "content": (
                "CRITICAL: Your entire response must be a single valid JSON object. "
                "Use the EXACT field names from the schema provided. "
                "Do NOT include the schema definition itself — produce actual data values. "
                "Do NOT wrap the JSON in markdown code fences."
            ),
        })

        response = await self.client.chat.completions.create(
            model=model,
            messages=enhanced_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        body = response.choices[0].message.content or "{}"

        # Strip markdown code fences if present
        stripped = body.strip()
        if stripped.startswith("```"):
            stripped = "\n".join(stripped.split("\n")[1:])
            if stripped.endswith("```"):
                stripped = stripped[:-3].strip()

        # If model returned an array, wrap it in the expected object
        if stripped.startswith("["):
            list_fields = [
                k for k, v in parameters.get("properties", {}).items()
                if isinstance(v, dict) and v.get("type") == "array"
            ]
            key = list_fields[0] if list_fields else "items"
            stripped = json.dumps({key: json.loads(stripped)})

        # Validate and fix the response
        content = stripped if stripped.startswith("{") else "{}"
        try:
            parsed = json.loads(content)
            parsed = _unwrap_structured_payload(parsed, parameters)
            # Fix field names in nested objects to match the schema
            parsed = _fix_field_names(parsed, parameters)
            content = json.dumps(parsed)
        except (json.JSONDecodeError, TypeError):
            pass

        usage = response.usage
        return SimpleNamespace(
            output_text=content,
            usage=SimpleNamespace(
                input_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
                output_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
            ),
        )


class Settings(BaseSettings):
    graphiti_api_key: str = "local-graphiti"
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str
    llm_api_style: str = "anthropic"
    llm_api_key: str
    llm_base_url: str | None = None
    llm_model_name: str | None = None
    llm_small_model_name: str | None = None
    embedding_api_key: str
    embedding_base_url: str | None = None
    embedding_model_name: str | None = None
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: str = "data"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


SETTINGS = Settings()
APP_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = (APP_DIR / SETTINGS.data_dir).resolve()
GROUPS_FILE = DATA_DIR / "groups.json"
THREADS_FILE = DATA_DIR / "threads.json"


def ensure_store() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for path in (GROUPS_FILE, THREADS_FILE):
        if not path.exists():
            path.write_text("{}", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    ensure_store()
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_store()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def require_auth(authorization: str | None = Header(default=None)) -> None:
    expected = f"Bearer {SETTINGS.graphiti_api_key}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def python_type(type_name: str | None) -> type[Any]:
    normalized = (type_name or "string").strip().lower()
    if normalized in {"string", "str", "text"}:
        return str
    if normalized in {"int", "integer"}:
        return int
    if normalized in {"float", "number", "double"}:
        return float
    if normalized in {"bool", "boolean"}:
        return bool
    return str


def build_entity_models(ontology: dict[str, Any]) -> dict[str, type[BaseModel]]:
    entity_models: dict[str, type[BaseModel]] = {}
    for entity in ontology.get("entity_types", []):
        name = entity.get("name")
        if not name:
            continue
        fields: dict[str, tuple[Any, None]] = {}
        for attr in entity.get("attributes", []):
            attr_name = attr.get("name")
            if not attr_name:
                continue
            fields[attr_name] = (python_type(attr.get("type")) | None, None)
        entity_models[name] = create_model(name, **fields)
    return entity_models


def build_edge_models(ontology: dict[str, Any]) -> dict[str, type[BaseModel]]:
    edge_models: dict[str, type[BaseModel]] = {}
    for edge in ontology.get("edge_types", []):
        name = edge.get("name")
        if not name:
            continue
        fields: dict[str, tuple[Any, None]] = {}
        for attr in edge.get("attributes", []):
            attr_name = attr.get("name")
            if not attr_name:
                continue
            fields[attr_name] = (python_type(attr.get("type")) | None, None)
        edge_models[name] = create_model(name, **fields)
    return edge_models


def build_edge_type_map(ontology: dict[str, Any]) -> dict[tuple[str, str], list[str]]:
    edge_type_map: dict[tuple[str, str], list[str]] = {}
    for edge in ontology.get("edge_types", []):
        edge_name = edge.get("name")
        if not edge_name:
            continue
        pairs = edge.get("source_targets") or [{"source": "Entity", "target": "Entity"}]
        for pair in pairs:
            source = pair.get("source") or "Entity"
            target = pair.get("target") or "Entity"
            edge_type_map.setdefault((source, target), []).append(edge_name)
    return edge_type_map or {("Entity", "Entity"): []}


def serialize_node(node: EntityNode | EpisodicNode) -> dict[str, Any]:
    return {
        "uuid_": getattr(node, "uuid", None) or getattr(node, "uuid_", ""),
        "name": getattr(node, "name", ""),
        "group_id": getattr(node, "group_id", ""),
        "labels": getattr(node, "labels", []),
        "summary": getattr(node, "summary", "") or "",
        "attributes": getattr(node, "attributes", {}) or {},
        "created_at": str(getattr(node, "created_at", "") or ""),
        "valid_at": str(getattr(node, "valid_at", "") or ""),
        "invalid_at": str(getattr(node, "invalid_at", "") or ""),
        "expired_at": str(getattr(node, "expired_at", "") or ""),
    }


def serialize_edge(edge: EntityEdge) -> dict[str, Any]:
    return {
        "uuid_": getattr(edge, "uuid", None) or getattr(edge, "uuid_", ""),
        "name": getattr(edge, "name", "") or "",
        "fact": getattr(edge, "fact", "") or "",
        "group_id": getattr(edge, "group_id", "") or "",
        "source_node_uuid": getattr(edge, "source_node_uuid", "") or "",
        "target_node_uuid": getattr(edge, "target_node_uuid", "") or "",
        "attributes": getattr(edge, "attributes", {}) or {},
        "created_at": str(getattr(edge, "created_at", "") or ""),
        "valid_at": str(getattr(edge, "valid_at", "") or ""),
        "invalid_at": str(getattr(edge, "invalid_at", "") or ""),
        "expired_at": str(getattr(edge, "expired_at", "") or ""),
    }


class GroupCreateRequest(BaseModel):
    group_id: str
    name: str
    description: str = ""


class OntologyRequest(BaseModel):
    entities: dict[str, Any] = Field(default_factory=dict)
    edges: dict[str, Any] = Field(default_factory=dict)


class EpisodeIn(BaseModel):
    content: str
    type: str = "text"


class EpisodeBatchRequest(BaseModel):
    episodes: list[EpisodeIn]


class SearchRequest(BaseModel):
    query: str
    limit: int = 10
    scope: str = "edges"
    reranker: str | None = None


class ThreadCreateRequest(BaseModel):
    thread_id: str | None = None
    user_id: str | None = None
    metadata: dict[str, Any] | None = None


class PassthroughCrossEncoder(CrossEncoderClient):
    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        return [(passage, float(len(passages) - index)) for index, passage in enumerate(passages)]


def normalize_anthropic_base_url(base_url: str | None) -> str | None:
    if not base_url:
        return None
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1/messages"):
        return normalized[: -len("/v1/messages")]
    if normalized.endswith("/v1"):
        return normalized[: -len("/v1")]
    return normalized


def _is_rate_limited_error(exc: Exception) -> bool:
    seen: set[int] = set()
    current: Exception | None = exc
    while current and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, GraphitiRateLimitError):
            return True
        message = str(current).lower()
        if "rate limit" in message or "too many requests" in message:
            return True
        current = current.__cause__ or current.__context__
    return False


async def _add_episode_with_retry(
    graphiti: Graphiti,
    *,
    group_id: str,
    episode_index: int,
    episode_content: str,
    entity_types: dict[str, type[BaseModel]] | None,
    edge_types: dict[str, type[BaseModel]] | None,
    edge_type_map: dict[tuple[str, str], list[str]],
    max_attempts: int = 4,
    base_delay_seconds: int = 15,
):
    for attempt in range(1, max_attempts + 1):
        try:
            return await graphiti.add_episode(
                name=f"{group_id}-episode-{episode_index}",
                episode_body=episode_content,
                source_description="MiroFish batch import",
                reference_time=datetime.now(timezone.utc),
                group_id=group_id,
                entity_types=entity_types or None,
                edge_types=edge_types or None,
                edge_type_map=edge_type_map,
            )
        except Exception as exc:
            if not _is_rate_limited_error(exc) or attempt == max_attempts:
                raise
            delay = min(90, base_delay_seconds * (2 ** (attempt - 1)))
            logger.warning(
                "Rate limited while ingesting episode %s for group %s; retrying in %ss (attempt %s/%s)",
                episode_index,
                group_id,
                delay,
                attempt,
                max_attempts - 1,
            )
            await asyncio.sleep(delay)


def build_graphiti() -> Graphiti:
    llm_config = LLMConfig(
        api_key=SETTINGS.llm_api_key,
        model=SETTINGS.llm_model_name,
        base_url=SETTINGS.llm_base_url,
        # Graphiti-core internally requests "small" models for some extraction
        # steps. Reuse the configured provider model unless a dedicated override
        # is supplied, otherwise it falls back to OpenAI-only defaults.
        small_model=SETTINGS.llm_small_model_name or SETTINGS.llm_model_name,
    )
    embedder_config = OpenAIEmbedderConfig(
        api_key=SETTINGS.embedding_api_key,
        base_url=SETTINGS.embedding_base_url,
        embedding_model=SETTINGS.embedding_model_name or "text-embedding-3-small",
    )
    llm_style = SETTINGS.llm_api_style.strip().lower()
    if llm_style == "anthropic":
        anthropic_client = AsyncAnthropic(
            api_key=SETTINGS.llm_api_key,
            base_url=normalize_anthropic_base_url(SETTINGS.llm_base_url),
            max_retries=1,
        )
        llm_client = AnthropicClient(config=llm_config, client=anthropic_client)
    elif llm_style == "openai":
        llm_client = ChatCompletionsClient(config=llm_config)
    else:
        raise ValueError(f"Unsupported LLM_API_STYLE: {SETTINGS.llm_api_style}")
    return Graphiti(
        SETTINGS.neo4j_uri,
        SETTINGS.neo4j_user,
        SETTINGS.neo4j_password,
        llm_client=llm_client,
        embedder=OpenAIEmbedder(config=embedder_config),
        cross_encoder=PassthroughCrossEncoder(),
    )


app = FastAPI(title="Local Graphiti Compat")

_graphiti: Graphiti | None = None


def get_graphiti() -> Graphiti:
    if _graphiti is None:
        raise RuntimeError("Graphiti not initialized")
    return _graphiti


@app.on_event("startup")
async def startup() -> None:
    global _graphiti
    ensure_store()
    _graphiti = build_graphiti()
    try:
        await _graphiti.build_indices_and_constraints()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"build_indices_and_constraints failed (non-fatal): {e}")


@app.on_event("shutdown")
async def shutdown() -> None:
    global _graphiti
    if _graphiti is not None:
        await _graphiti.close()
        _graphiti = None


@app.get("/healthcheck")
async def healthcheck() -> JSONResponse:
    return JSONResponse({"status": "healthy"})


@app.post("/v1/groups")
async def create_group(payload: GroupCreateRequest, _: None = Depends(require_auth)) -> dict[str, Any]:
    groups = load_json(GROUPS_FILE)
    groups[payload.group_id] = {
        "group_id": payload.group_id,
        "name": payload.name,
        "description": payload.description,
        "ontology": None,
    }
    save_json(GROUPS_FILE, groups)
    return groups[payload.group_id]


@app.post("/v1/groups/{group_id}/ontology")
async def set_ontology(
    group_id: str,
    payload: OntologyRequest,
    _: None = Depends(require_auth),
) -> dict[str, Any]:
    groups = load_json(GROUPS_FILE)
    group = groups.get(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    group["ontology"] = {
        "entity_types": list(payload.entities.values()),
        "edge_types": list(payload.edges.values()),
    }
    groups[group_id] = group
    save_json(GROUPS_FILE, groups)
    return {"ok": True}


@app.post("/v1/groups/{group_id}/episodes:batch")
async def add_episode_batch(
    group_id: str,
    payload: EpisodeBatchRequest,
    _: None = Depends(require_auth),
) -> list[dict[str, Any]]:
    groups = load_json(GROUPS_FILE)
    group = groups.get(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    ontology = group.get("ontology") or {}
    entity_types = build_entity_models(ontology)
    edge_types = build_edge_models(ontology)
    edge_type_map = build_edge_type_map(ontology)

    graphiti = get_graphiti()
    results: list[dict[str, Any]] = []
    for index, episode in enumerate(payload.episodes, start=1):
        if index > 1:
            await asyncio.sleep(1)  # brief pause between episodes
        try:
            outcome = await _add_episode_with_retry(
                graphiti,
                group_id=group_id,
                episode_index=index,
                episode_content=episode.content,
                entity_types=entity_types,
                edge_types=edge_types,
                edge_type_map=edge_type_map,
            )
        except Exception as exc:
            logger.exception("Failed to add episode %s for group %s", index, group_id)
            status_code = 429 if _is_rate_limited_error(exc) else 500
            detail_prefix = (
                "Graphiti batch ingest rate-limited"
                if status_code == 429
                else "Graphiti batch ingest failed"
            )
            raise HTTPException(
                status_code=status_code,
                detail=f"{detail_prefix} for episode {index}: {exc}",
            ) from exc
        results.append(
            {
                "uuid_": outcome.episode.uuid,
                "processed": True,
            }
        )
    return results


@app.get("/v1/episodes/{episode_uuid}")
async def get_episode(episode_uuid: str, _: None = Depends(require_auth)) -> dict[str, Any]:
    graphiti = get_graphiti()
    episode = await graphiti.nodes.episode.get_by_uuid(episode_uuid)
    data = serialize_node(episode)
    data["processed"] = True
    return data


@app.get("/v1/groups/{group_id}/nodes")
async def get_group_nodes(
    group_id: str,
    limit: int = 100,
    uuid_cursor: str | None = None,
    _: None = Depends(require_auth),
) -> list[dict[str, Any]]:
    graphiti = get_graphiti()
    nodes = await graphiti.nodes.entity.get_by_group_ids([group_id], limit=limit, uuid_cursor=uuid_cursor)
    return [serialize_node(node) for node in nodes]


@app.get("/v1/groups/{group_id}/edges")
async def get_group_edges(
    group_id: str,
    limit: int = 100,
    uuid_cursor: str | None = None,
    _: None = Depends(require_auth),
) -> list[dict[str, Any]]:
    graphiti = get_graphiti()
    edges = await graphiti.edges.entity.get_by_group_ids([group_id], limit=limit, uuid_cursor=uuid_cursor)
    return [serialize_edge(edge) for edge in edges]


@app.get("/v1/nodes/{node_uuid}")
async def get_node(node_uuid: str, _: None = Depends(require_auth)) -> dict[str, Any]:
    graphiti = get_graphiti()
    node = await graphiti.nodes.entity.get_by_uuid(node_uuid)
    return serialize_node(node)


@app.get("/v1/nodes/{node_uuid}/edges")
async def get_node_edges(node_uuid: str, _: None = Depends(require_auth)) -> list[dict[str, Any]]:
    graphiti = get_graphiti()
    edges = await graphiti.edges.entity.get_by_node_uuid(node_uuid)
    return [serialize_edge(edge) for edge in edges]


@app.get("/v1/edges/{edge_uuid}")
async def get_edge(edge_uuid: str, _: None = Depends(require_auth)) -> dict[str, Any]:
    graphiti = get_graphiti()
    edge = await graphiti.edges.entity.get_by_uuid(edge_uuid)
    return serialize_edge(edge)


@app.post("/v1/groups/{group_id}/search")
async def search_group(
    group_id: str,
    payload: SearchRequest,
    _: None = Depends(require_auth),
) -> dict[str, Any]:
    graphiti = get_graphiti()
    edges = await graphiti.search(payload.query, group_ids=[group_id], num_results=payload.limit)
    node_map: dict[str, dict[str, Any]] = {}
    if payload.scope != "edges":
        for edge in edges:
            for node_uuid in (edge.source_node_uuid, edge.target_node_uuid):
                if not node_uuid or node_uuid in node_map:
                    continue
                try:
                    node = await graphiti.nodes.entity.get_by_uuid(node_uuid)
                    node_map[node_uuid] = serialize_node(node)
                except Exception:
                    continue
    return {
        "facts": [serialize_edge(edge) for edge in edges],
        "edges": [serialize_edge(edge) for edge in edges],
        "nodes": list(node_map.values()),
    }


@app.delete("/v1/groups/{group_id}")
async def delete_group(group_id: str, _: None = Depends(require_auth)) -> dict[str, Any]:
    graphiti = get_graphiti()
    await graphiti.nodes.entity.delete_by_group_id(group_id)
    await graphiti.nodes.episode.delete_by_group_id(group_id)
    groups = load_json(GROUPS_FILE)
    groups.pop(group_id, None)
    save_json(GROUPS_FILE, groups)
    return {"ok": True}


@app.get("/v1/threads")
async def list_threads(
    user_id: str | None = None,
    limit: int = 20,
    page_token: str | None = None,
    _: None = Depends(require_auth),
) -> dict[str, Any]:
    threads = load_json(THREADS_FILE)
    values = list(threads.values())
    if user_id:
        values = [item for item in values if item.get("user_id") == user_id]
    if page_token:
        values = [item for item in values if item.get("thread_id") > page_token]
    values = values[:limit]
    return {"threads": values, "next_page_token": values[-1]["thread_id"] if len(values) == limit else None}


@app.post("/v1/threads")
async def create_thread(payload: ThreadCreateRequest, _: None = Depends(require_auth)) -> dict[str, Any]:
    threads = load_json(THREADS_FILE)
    thread_id = payload.thread_id or f"thread_{uuid4().hex[:12]}"
    thread = {
        "thread_id": thread_id,
        "user_id": payload.user_id,
        "metadata": payload.metadata or {},
    }
    threads[thread_id] = thread
    save_json(THREADS_FILE, threads)
    return thread


@app.get("/v1/threads/{thread_id}")
async def get_thread(thread_id: str, _: None = Depends(require_auth)) -> dict[str, Any]:
    threads = load_json(THREADS_FILE)
    thread = threads.get(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


@app.delete("/v1/threads/{thread_id}")
async def delete_thread(thread_id: str, _: None = Depends(require_auth)) -> dict[str, Any]:
    threads = load_json(THREADS_FILE)
    threads.pop(thread_id, None)
    save_json(THREADS_FILE, threads)
    return {"ok": True}
