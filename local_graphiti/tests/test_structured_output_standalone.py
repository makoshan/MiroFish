"""Standalone regression checks for structured JSON normalization."""

from graphiti_compat.app import _fix_field_names, _unwrap_structured_payload


schema = {
    "type": "object",
    "properties": {
        "extracted_entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "entity_type_id": {"type": "integer"},
                },
            },
        }
    },
}


wrapped = {"properties": {"extracted_entities": []}}
assert _unwrap_structured_payload(wrapped, schema) == {"extracted_entities": []}

double_wrapped = {"result": {"properties": {"extracted_entities": []}}}
assert _unwrap_structured_payload(double_wrapped, schema) == {"extracted_entities": []}

renamed = {"properties": {"nodes": [{"name": "Alice", "entity_type_id": 1}]}}
normalized = _fix_field_names(_unwrap_structured_payload(renamed, schema), schema)
assert normalized["extracted_entities"][0]["name"] == "Alice"

print("ok")
