from __future__ import annotations

import json
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from mosaic.dataflows.frozen_research_digest import (
    FrozenResearchDigestBuilder,
    normalize_openai_chat_completions_endpoint,
)
from mosaic.scorecard.canonical_json import canonical_hash


@pytest.mark.parametrize(
    "value",
    [
        "https://gateway.example/zen/go/v1",
        "https://gateway.example/zen/go/v1/",
        "https://gateway.example/zen/go/v1/chat/completions",
        "https://gateway.example/zen/go/v1/chat/completions/",
    ],
)
def test_digest_endpoint_normalization_accepts_base_or_complete_endpoint(value: str) -> None:
    assert (
        normalize_openai_chat_completions_endpoint(value)
        == "https://gateway.example/zen/go/v1/chat/completions"
    )


@pytest.mark.parametrize(
    "value",
    [
        "not-a-url",
        "ftp://gateway.example/v1",
        "https://embedded@gateway.example/v1",
        "https://gateway.example/v1?key=secret",
        "https://gateway.example/v1#fragment",
    ],
)
def test_digest_endpoint_normalization_rejects_unsafe_forms(value: str) -> None:
    with pytest.raises(ValueError, match="endpoint"):
        normalize_openai_chat_completions_endpoint(value)


def test_digest_builder_uses_agent_provider_env_and_returns_frozen_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "MOSAIC_LLM_BASE_URL",
        "https://gateway.example/zen/go/v1/chat/completions",
    )
    monkeypatch.setenv("MOSAIC_LLM_MODEL", "remote-model")
    monkeypatch.setenv("MOSAIC_LLM_API_KEY", "test-key")
    monkeypatch.setenv("MOSAIC_LLM_MAX_TOKENS", "4096")
    monkeypatch.setenv("MOSAIC_LLM_USER_AGENT", "mosaic-audit/2.0")
    seen: dict[str, object] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "summary": "policy support remains selective",
                                        "evidence_points": ["credit support was reiterated"],
                                        "counterevidence": ["implementation remains uneven"],
                                        "uncertainties": ["timing is not specified"],
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode()

    def urlopen(request: Request, timeout: int):
        seen["url"] = request.full_url
        seen["headers"] = dict(request.header_items())
        seen["body"] = json.loads(bytes(request.data or b"").decode())
        seen["timeout"] = timeout
        return Response()

    builder = FrozenResearchDigestBuilder(urlopen=urlopen)
    result = builder(
        "get_industry_policy_digest",
        "licensed source prose",
        {"as_of": "2026-07-09", "lookback_days": 30, "source": "govcn"},
    )

    assert seen["url"] == "https://gateway.example/zen/go/v1/chat/completions"
    assert seen["headers"] == {
        "Authorization": "Bearer test-key",
        "Content-type": "application/json",
        "User-agent": "mosaic-audit/2.0",
    }
    assert seen["body"] == {
        "model": "remote-model",
        "messages": seen["body"]["messages"],
        "temperature": 0,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
    }
    assert "licensed source prose" in seen["body"]["messages"][1]["content"]
    assert result["model_hash"] == canonical_hash(
        {"provider": "openai_compatible", "model": "remote-model"}
    )
    assert result["prompt_hash"].startswith("sha256:")
    digest = json.loads(result["digest"])
    assert digest["summary"] == "policy support remains selective"
    assert "licensed source prose" not in result["digest"]


def test_digest_builder_retries_transient_http_errors_only() -> None:
    calls = 0
    delays: list[float] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self) -> bytes:
            content = {
                "summary": "retry succeeded",
                "evidence_points": [],
                "counterevidence": [],
                "uncertainties": [],
            }
            return json.dumps(
                {"choices": [{"message": {"content": json.dumps(content)}}]}
            ).encode()

    def transient_then_success(request: Request, timeout: int):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise HTTPError(request.full_url, 503, "unavailable", None, None)
        return Response()

    builder = FrozenResearchDigestBuilder(
        endpoint="https://gateway.example/v1",
        model="remote-model",
        api_key="test-key",
        urlopen=transient_then_success,
        sleep=delays.append,
        retry_delay_seconds=0.01,
    )
    assert json.loads(
        builder("get_broker_research", "source", {"ticker": "600000.SH"})[
            "digest"
        ]
    )["summary"] == "retry succeeded"
    assert calls == 2
    assert delays == [0.01]

    bad_request_calls = 0
    bad_request_delays: list[float] = []

    def bad_request(request: Request, timeout: int):
        nonlocal bad_request_calls
        bad_request_calls += 1
        raise HTTPError(request.full_url, 400, "bad request", None, None)

    bad_request_builder = FrozenResearchDigestBuilder(
        endpoint="https://gateway.example/v1",
        model="remote-model",
        api_key="test-key",
        urlopen=bad_request,
        sleep=bad_request_delays.append,
        retry_delay_seconds=0.01,
    )
    with pytest.raises(ValueError, match="request failed"):
        bad_request_builder(
            "get_broker_research", "different source", {"ticker": "600000.SH"}
        )
    assert bad_request_calls == 1
    assert bad_request_delays == []


@pytest.mark.parametrize("invalid_content", ["", "not-json"])
def test_digest_builder_retries_invalid_provider_content(invalid_content: str) -> None:
    calls = 0
    delays: list[float] = []

    class Response:
        def __init__(self, content: str) -> None:
            self.content = content

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self) -> bytes:
            return json.dumps(
                {"choices": [{"message": {"content": self.content}}]}
            ).encode()

    def invalid_then_success(request: Request, timeout: int):
        nonlocal calls
        calls += 1
        if calls == 1:
            return Response(invalid_content)
        return Response(
            json.dumps(
                {
                    "summary": "retry succeeded",
                    "evidence_points": [],
                    "counterevidence": [],
                    "uncertainties": [],
                }
            )
        )

    builder = FrozenResearchDigestBuilder(
        endpoint="https://gateway.example/v1",
        model="remote-model",
        api_key="test-key",
        urlopen=invalid_then_success,
        max_attempts=2,
        sleep=delays.append,
        retry_delay_seconds=0.01,
    )

    digest = json.loads(
        builder("get_broker_research", "source", {"ticker": "600000.SH"})[
            "digest"
        ]
    )
    assert digest["summary"] == "retry succeeded"
    assert calls == 2
    assert delays == [0.01]


def test_digest_builder_fails_closed_on_missing_env_or_malformed_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MOSAIC_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("MOSAIC_LLM_MODEL", raising=False)
    monkeypatch.delenv("MOSAIC_LLM_API_KEY", raising=False)
    with pytest.raises(ValueError, match="MOSAIC_LLM_BASE_URL"):
        FrozenResearchDigestBuilder()

    builder = FrozenResearchDigestBuilder(
        endpoint="https://gateway.example/v1",
        model="remote-model",
        api_key="test-key",
        urlopen=lambda request, timeout: pytest.fail("construction must not call transport"),
    )
    builder.urlopen = lambda request, timeout: _MalformedResponse()
    with pytest.raises(ValueError, match="digest response"):
        builder("get_stock_research", "raw", {"ticker": "600000.SH"})


class _MalformedResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return json.dumps({"choices": [{"message": {"content": "not-json"}}]}).encode()
