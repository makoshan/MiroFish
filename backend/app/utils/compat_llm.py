"""
LLM compatibility layer.

Supports both OpenAI-compatible chat completions APIs and
Anthropic-compatible messages APIs behind a shared interface.
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx
from openai import OpenAI

from ..config import Config


@dataclass
class LLMCompletion:
    """Normalized completion payload returned by the compatibility client."""

    content: str
    finish_reason: str = "stop"


class CompatibleLLMClient:
    """Provider-agnostic chat client used by the backend generators."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        api_style: Optional[str] = None,
        timeout: float = 120.0,
        trust_env: Optional[bool] = None,
    ):
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = (base_url or Config.LLM_BASE_URL or "").rstrip("/")
        self.model = model or Config.LLM_MODEL_NAME
        self.api_style = (api_style or Config.LLM_API_STYLE or "openai").lower()
        self.timeout = timeout
        self.trust_env = Config.LLM_TRUST_ENV if trust_env is None else trust_env

        if not self.api_key:
            raise ValueError("LLM_API_KEY 未配置")

        if self.api_style == "anthropic":
            self.client = httpx.Client(timeout=self.timeout, trust_env=self.trust_env)
        else:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url or "https://api.openai.com/v1",
                timeout=self.timeout,
            )

    def create_chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> LLMCompletion:
        """Create a normalized chat completion across providers."""
        if self.api_style == "anthropic":
            return self._create_anthropic_completion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            kwargs["response_format"] = response_format

        response = self.client.chat.completions.create(**kwargs)
        return LLMCompletion(
            content=response.choices[0].message.content or "",
            finish_reason=response.choices[0].finish_reason or "stop",
        )

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Return response text only."""
        completion = self.create_chat_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        return self._clean_content(completion.content)

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        """Return a parsed JSON object from the model response."""
        response = self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        cleaned_response = response.strip()
        cleaned_response = re.sub(r"^```(?:json)?\s*\n?", "", cleaned_response, flags=re.IGNORECASE)
        cleaned_response = re.sub(r"\n?```\s*$", "", cleaned_response)
        cleaned_response = cleaned_response.strip()

        return json.loads(cleaned_response)

    def _create_anthropic_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: Optional[Dict[str, Any]],
    ) -> LLMCompletion:
        system_prompt, converted_messages = self._split_messages(messages)

        if response_format and response_format.get("type") == "json_object":
            json_instruction = (
                "Return only a valid JSON object. Do not include markdown code fences "
                "or any explanation outside the JSON object."
            )
            system_prompt = f"{system_prompt}\n\n{json_instruction}".strip() if system_prompt else json_instruction

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": converted_messages or [{"role": "user", "content": ""}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if system_prompt:
            payload["system"] = system_prompt

        response = self.client.post(
            self._anthropic_messages_url(),
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()

        body = response.json()
        text_parts = []
        for block in body.get("content", []):
            if block.get("type") == "text" and block.get("text"):
                text_parts.append(block["text"])

        return LLMCompletion(
            content="\n".join(text_parts).strip(),
            finish_reason=self._normalize_anthropic_finish_reason(body.get("stop_reason")),
        )

    def _anthropic_messages_url(self) -> str:
        """Normalize an Anthropic-compatible base URL to a messages endpoint."""
        if self.base_url.endswith("/v1/messages"):
            return self.base_url
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/messages"
        return f"{self.base_url}/v1/messages"

    @staticmethod
    def _split_messages(messages: List[Dict[str, str]]) -> tuple[str, List[Dict[str, str]]]:
        """Convert mixed role messages into Anthropic-compatible payload fields."""
        system_parts: List[str] = []
        converted: List[Dict[str, str]] = []

        for message in messages:
            role = message.get("role", "user")
            content = str(message.get("content", ""))
            if role == "system":
                system_parts.append(content)
                continue
            if role not in {"user", "assistant"}:
                role = "user"
            converted.append({"role": role, "content": content})

        return "\n\n".join(system_parts).strip(), converted

    @staticmethod
    def _normalize_anthropic_finish_reason(stop_reason: Optional[str]) -> str:
        if stop_reason == "max_tokens":
            return "length"
        if stop_reason in {"end_turn", "stop_sequence", None}:
            return "stop"
        return stop_reason

    @staticmethod
    def _clean_content(content: str) -> str:
        # Some models emit <think> blocks; strip them before downstream parsing.
        return re.sub(r"<think>[\s\S]*?</think>", "", content or "").strip()
