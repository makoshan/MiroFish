"""Backward-compatible graph client factory.

Historically this project used Zep Cloud SDK directly.
Now we route all graph operations through Graphiti.
"""

from __future__ import annotations

from .graph_client import GraphitiClient, create_graphiti_client


def create_zep_client(api_key: str) -> GraphitiClient:
    """Build a Graphiti client with the old factory name for compatibility."""
    return create_graphiti_client(api_key)
