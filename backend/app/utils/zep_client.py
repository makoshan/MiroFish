"""
Shared Zep client factory.

Creates Zep SDK clients with a consistent httpx configuration so the
backend does not accidentally inherit broken system proxy settings.
"""

from __future__ import annotations

import httpx
from zep_cloud.client import Zep

from ..config import Config


def create_zep_client(api_key: str) -> Zep:
    """Build a Zep client with explicit httpx settings."""
    httpx_client = httpx.Client(
        timeout=Config.ZEP_TIMEOUT_SECONDS,
        trust_env=Config.ZEP_TRUST_ENV,
        follow_redirects=True,
    )
    return Zep(
        api_key=api_key,
        timeout=Config.ZEP_TIMEOUT_SECONDS,
        httpx_client=httpx_client,
    )
