"""Trusted private-source digest builder for frozen adaptive queries."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from mosaic.scorecard.canonical_json import canonical_hash


_USER_AGENT = "mosaic-rke/0.1.0"
_RETRYABLE_HTTP_STATUSES = {408, 425, 429}
_PROMPT_CONTRACT_VERSION = "frozen_research_digest_prompt_v2"
_DIGEST_FIELDS = {
    "summary",
    "evidence_points",
    "counterevidence",
    "uncertainties",
}
_DIGEST_TOOLS = {
    "get_broker_research",
    "get_industry_policy_digest",
    "get_stock_research",
}
_SYSTEM_PROMPT = (
    "You create compact research digests for an audited investment-analysis tool. "
    "Use only the supplied source. Return one JSON object with exactly summary, "
    "evidence_points, counterevidence, and uncertainties. The last three fields are "
    "arrays of short strings. Separate claims from counterevidence, preserve uncertainty, "
    "do not give trading instructions, and do not quote long source passages."
)


def _env(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else None


def normalize_openai_chat_completions_endpoint(value: str) -> str:
    """Normalize an OpenAI-compatible base or full endpoint to chat/completions."""
    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("MOSAIC LLM endpoint is invalid")
    path = parsed.path.rstrip("/")
    suffix = "/chat/completions"
    if path.endswith(suffix):
        path = path[: -len(suffix)].rstrip("/")
    path = f"{path}{suffix}"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _positive_int(value: int | str | None, *, field: str, default: int) -> int:
    raw: Any = default if value is None else value
    if isinstance(raw, bool):
        raise ValueError(f"{field} must be a positive integer")
    try:
        parsed = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a positive integer") from exc
    if parsed <= 0 or str(parsed) != str(raw).strip():
        raise ValueError(f"{field} must be a positive integer")
    return parsed


def _response_content(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        raise ValueError("digest response must be an object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        raise ValueError("digest response choices are missing")
    message = choices[0].get("message")
    if not isinstance(message, Mapping):
        raise ValueError("digest response message is missing")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("digest response content is missing")
    return content.strip()


def _digest_object(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```json") and cleaned.endswith("```"):
        cleaned = cleaned[7:-3].strip()
    elif cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned[3:-3].strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError("digest response content is not valid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != _DIGEST_FIELDS:
        raise ValueError("digest response fields do not match the contract")
    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 1200:
        raise ValueError("digest response summary is invalid")
    for field in ("evidence_points", "counterevidence", "uncertainties"):
        values = payload.get(field)
        if (
            not isinstance(values, list)
            or len(values) > 12
            or any(
                not isinstance(value, str)
                or not value.strip()
                or len(value) > 600
                for value in values
            )
        ):
            raise ValueError(f"digest response {field} is invalid")
    return {
        "summary": summary.strip(),
        **{
            field: [value.strip() for value in payload[field]]
            for field in ("evidence_points", "counterevidence", "uncertainties")
        },
    }


def _retryable_request_error(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in _RETRYABLE_HTTP_STATUSES or exc.code >= 500
    return isinstance(
        exc,
        (
            OSError,
            urllib.error.URLError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ),
    )


class FrozenResearchDigestBuilder:
    """Call the configured Agent provider and return auditable digest lineage."""

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        max_tokens: int | None = None,
        timeout_seconds: int = 120,
        urlopen: Callable[..., Any] = urllib.request.urlopen,
        user_agent: str | None = None,
        max_attempts: int = 3,
        retry_delay_seconds: float = 0.25,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        raw_endpoint = endpoint or _env("MOSAIC_LLM_BASE_URL")
        if not raw_endpoint:
            raise ValueError("MOSAIC_LLM_BASE_URL is required for frozen research digests")
        self.endpoint = normalize_openai_chat_completions_endpoint(raw_endpoint)
        self.model = str(model or _env("MOSAIC_LLM_MODEL") or "").strip()
        if not self.model:
            raise ValueError("MOSAIC_LLM_MODEL is required for frozen research digests")
        self.api_key = str(api_key or _env("MOSAIC_LLM_API_KEY") or "").strip()
        if not self.api_key:
            raise ValueError("MOSAIC_LLM_API_KEY is required for frozen research digests")
        self.max_tokens = _positive_int(
            max_tokens if max_tokens is not None else _env("MOSAIC_LLM_MAX_TOKENS"),
            field="MOSAIC_LLM_MAX_TOKENS",
            default=2048,
        )
        self.timeout_seconds = _positive_int(
            timeout_seconds,
            field="digest timeout_seconds",
            default=120,
        )
        raw_user_agent = (
            user_agent
            if user_agent is not None
            else (_env("MOSAIC_LLM_USER_AGENT") or _USER_AGENT)
        )
        self.user_agent = str(raw_user_agent).strip()
        if not self.user_agent or "\r" in self.user_agent or "\n" in self.user_agent:
            raise ValueError("MOSAIC_LLM_USER_AGENT is invalid")
        if (
            isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
            or not 1 <= max_attempts <= 5
        ):
            raise ValueError("digest max_attempts must be an integer in [1, 5]")
        if (
            isinstance(retry_delay_seconds, bool)
            or not isinstance(retry_delay_seconds, (int, float))
            or retry_delay_seconds < 0
        ):
            raise ValueError("digest retry_delay_seconds must be non-negative")
        self.max_attempts = max_attempts
        self.retry_delay_seconds = float(retry_delay_seconds)
        self.sleep = sleep
        self.urlopen = urlopen

    def __call__(
        self,
        tool_id: str,
        raw_payload: str,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        if tool_id not in _DIGEST_TOOLS:
            raise ValueError("unsupported frozen research digest tool")
        if not isinstance(raw_payload, str) or not raw_payload:
            raise ValueError("frozen research digest source payload must be non-empty")
        if not isinstance(args, dict):
            raise ValueError("frozen research digest args must be an object")
        source_payload_hash = canonical_hash({"text": raw_payload})
        prompt_body = {
            "prompt_contract_version": _PROMPT_CONTRACT_VERSION,
            "tool_id": tool_id,
            "source_payload_hash": source_payload_hash,
        }
        user_prompt = (
            f"Request metadata:\n{json.dumps(prompt_body, ensure_ascii=False, sort_keys=True)}"
            f"\n\nSource material:\n{raw_payload}"
        )
        request_payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": self.user_agent,
            },
            method="POST",
        )
        for attempt in range(self.max_attempts):
            try:
                with self.urlopen(request, timeout=self.timeout_seconds) as response:
                    response_payload = json.loads(response.read().decode("utf-8"))
                break
            except (
                OSError,
                urllib.error.URLError,
                UnicodeDecodeError,
                json.JSONDecodeError,
            ) as exc:
                if not _retryable_request_error(exc) or attempt + 1 == self.max_attempts:
                    raise ValueError("frozen research digest request failed") from exc
                self.sleep(self.retry_delay_seconds * (2**attempt))
        digest = _digest_object(_response_content(response_payload))
        return {
            "digest": json.dumps(
                digest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "model_hash": canonical_hash(
                {"provider": "openai_compatible", "model": self.model}
            ),
            "prompt_hash": canonical_hash(
                {
                    **prompt_body,
                    "system_prompt": _SYSTEM_PROMPT,
                }
            ),
        }


__all__ = [
    "FrozenResearchDigestBuilder",
    "normalize_openai_chat_completions_endpoint",
]
