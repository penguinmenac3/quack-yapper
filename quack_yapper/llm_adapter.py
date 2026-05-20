from __future__ import annotations

import base64
import logging
import os
from abc import ABC, abstractmethod

import httpx

from quack_yapper.config import AIConfig

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(300.0, connect=10.0)


class LLMAdapter(ABC):
    @abstractmethod
    def complete(self, system_prompt: str, user_text: str, image_bytes: bytes | None = None) -> str:
        """Blocking. Safe to call from a QThread; never call from the main thread."""
        ...

    def cancel(self) -> None:
        """Close the underlying connection. Causes complete() to raise."""
        ...


class OpenAIAdapter(LLMAdapter):
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._client = httpx.Client(timeout=_TIMEOUT)

    def complete(self, system_prompt: str, user_text: str, image_bytes: bytes | None = None) -> str:
        if image_bytes is not None:
            b64 = base64.b64encode(image_bytes).decode()
            user_content = [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]
        else:
            user_content = user_text

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        resp = self._client.post(
            f"{self._base_url}/chat/completions",
            json={"model": self._model, "messages": messages},
            headers={"Authorization": f"Bearer {self._api_key or 'unused'}"},
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def cancel(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass
        self._client = httpx.Client(timeout=_TIMEOUT)


class BedrockAdapter(LLMAdapter):
    def __init__(self, base_url: str, region: str, api_key: str, model: str) -> None:
        self._base_url = base_url
        self._region = region
        self._model = model
        if api_key:
            os.environ["AWS_BEARER_TOKEN_BEDROCK"] = api_key
        self._client = self._make_client()

    def _make_client(self):
        import boto3
        from botocore.config import Config

        kwargs: dict = {
            "region_name": self._region,
            "config": Config(connect_timeout=10, read_timeout=300),
        }
        if self._base_url:
            kwargs["endpoint_url"] = self._base_url
        return boto3.client("bedrock-runtime", **kwargs)

    def complete(self, system_prompt: str, user_text: str, image_bytes: bytes | None = None) -> str:
        if image_bytes is not None:
            content = [
                {"text": user_text},
                {"image": {"format": "png", "source": {"bytes": image_bytes}}},
            ]
        else:
            content = [{"text": user_text}]

        resp = self._client.converse(
            modelId=self._model,
            system=[{"text": system_prompt}],
            messages=[{"role": "user", "content": content}],
        )
        return resp["output"]["message"]["content"][0]["text"]

    def cancel(self) -> None:
        try:
            self._client._endpoint.http_session.close()
        except Exception:
            pass


def make_adapter(config: AIConfig) -> LLMAdapter:
    if config.provider == "bedrock":
        return BedrockAdapter(
            base_url=config.base_url,
            region=config.region,
            api_key=config.api_key,
            model=config.model,
        )
    return OpenAIAdapter(
        base_url=config.base_url,
        api_key=config.api_key,
        model=config.model,
    )
