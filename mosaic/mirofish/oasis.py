"""Real-engine adapter: drive a deployed 666ghj/MiroFish service over its actual
multi-step async API.

7M Step 3 (direction 1, post-clone). Verified against the real backend cloned to
~/Project/MiroFish: there is NO synchronous ``/scenarios`` endpoint. The real
pipeline is stateful + async and returns a free-form Chinese markdown *prediction
report* (public-opinion / event simulation), not A-share price paths:

    1. POST /api/graph/ontology/generate   (multipart: seed file + requirement) → project_id
    2. POST /api/graph/build {project_id}   → task_id  (poll /api/graph/task/<id>)
    3. POST /api/simulation/create {project_id} → simulation_id
    4. POST /api/simulation/prepare {simulation_id} → task_id (poll /prepare/status)
    5. POST /api/report/generate {simulation_id}    → task_id (poll /generate/status)
    6. GET  /api/report/<report_id>          → { markdown_content, outline }

This adapter walks that chain, then **lossily** maps the report's directional
sentiment to our montecarlo-shaped scenario dict (the report has no OHLCV — we
derive a regime + CSI300 drift from bullish/bearish language and synthesise a
minimal price path). The lossiness is inherent: MiroFish predicts narratives,
not prices. Honest scope: needs a live service + LLM_API_KEY + ZEP_API_KEY +
per-run cost; no live integration is possible in CI, so only the request
sequencing, polling, and report→scenario mapping are unit-tested with a fake
transport.

Pure stdlib (urllib), no new dependency; deps-light (no numpy).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Mapping, Optional

DEFAULT_TIMEOUT = 60       # per-request socket timeout
DEFAULT_POLL_TIMEOUT = 1800  # max seconds to wait for an async step (sim is slow)
_POLL_INTERVAL = 5
_DEFAULT_MAX_ROUNDS = 5     # keep sims short by default — full OASIS runs are slow + LLM-costly
_RUN_DONE = ("completed", "stopped")   # terminal run-status (success)
_RUN_FAILED = "failed"


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _positive_int(value: Any, default: int) -> int:
    """Coerce to a positive int, falling back to ``default`` for non-int/<=0
    values — so a bad MOSAIC_MIROFISH_MAX_ROUNDS can never drop or corrupt the
    run cap (the cap exists precisely to avoid long, costly OASIS runs)."""
    n = _safe_int(value, default)
    return n if n > 0 else default

# A-share scenario scaffold reused for the montecarlo-shaped output.
_PROBE = "000300.SH"
_SCENARIO_PROB = {"base": 0.5, "bull": 0.2, "bear": 0.2, "tail_up": 0.05, "tail_down": 0.05}
_SCENARIO_DRIFT = {"base": 0.0, "bull": 0.10, "bear": -0.10, "tail_up": 0.25, "tail_down": -0.25}
_BULL_WORDS = ("利好", "上涨", "看多", "乐观", "反弹", "bullish", "rally", "rise", "positive")
_BEAR_WORDS = ("利空", "下跌", "看空", "悲观", "回调", "崩", "bearish", "crash", "fall", "risk-off")


class MiroFishUnavailable(RuntimeError):
    """Service unreachable, errored, timed out, or returned an unexpected shape."""


class OasisMiroFishEngine:
    """``SwarmEngine``-shaped client for a deployed MiroFish service's real
    multi-step API. ``base_url`` defaults to ``$MOSAIC_MIROFISH_URL``."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
        poll_timeout: int = DEFAULT_POLL_TIMEOUT,
        max_rounds: Optional[int] = None,
    ) -> None:
        self._base_url = (base_url or os.environ.get("MOSAIC_MIROFISH_URL") or "").rstrip("/")
        self._timeout = timeout
        self._poll_timeout = poll_timeout
        # Always resolve to a positive cap (ctor arg wins, else env, else default).
        self._max_rounds = _positive_int(
            max_rounds if max_rounds is not None else os.environ.get("MOSAIC_MIROFISH_MAX_ROUNDS"),
            _DEFAULT_MAX_ROUNDS,
        )
        # Escape hatch for debugging report-only behaviour: skip the (slow) sim run.
        self._skip_start = os.environ.get("MOSAIC_MIROFISH_SKIP_START", "").lower() in (
            "1", "true", "yes",
        )

    # ---- SwarmEngine interface -------------------------------------------

    def generate_all_scenarios(
        self,
        start_prices: Optional[Mapping[str, float]],
        num_days: int,
        seed: Optional[int],
        scenarios: Optional[list[str]],
    ) -> list[dict[str, Any]]:
        if not self._base_url:
            raise MiroFishUnavailable(
                "engine='oasis' needs a deployed MiroFish service: set MOSAIC_MIROFISH_URL "
                "(e.g. http://localhost:5001)."
            )
        report_md = self._run_pipeline(seed)
        sentiment = self._sentiment(report_md)  # -1..+1
        start = float((start_prices or {}).get(_PROBE, 3500.0))
        types = scenarios or ["base", "bull", "bear", "tail_up", "tail_down"]
        return [self._scenario(t, start, num_days, sentiment, report_md) for t in types]

    # ---- real multi-step pipeline ----------------------------------------

    def _run_pipeline(self, seed: Optional[int]) -> str:
        requirement = (
            "Predict the near-term A-share market regime (CSI300 direction, "
            "risk appetite, tail risks) from the seed signals."
        )
        seed_text = f"MOSAIC A-share scenario seed (seed={seed}).\n{requirement}\n"
        project_id = self._ontology(seed_text, requirement)
        self._poll(
            "/api/graph/task/", self._post_json("/api/graph/build", {"project_id": project_id}),
            key="task_id", via_get=True,
        )
        sim = self._post_json("/api/simulation/create", {"project_id": project_id})
        simulation_id = _dig(sim, "simulation_id")
        if not simulation_id:
            raise MiroFishUnavailable("simulation/create returned no simulation_id")
        prep = self._post_json("/api/simulation/prepare", {"simulation_id": simulation_id})
        self._poll_status("/api/simulation/prepare/status", _dig(prep, "task_id"), simulation_id)
        # Run the actual OASIS multi-agent simulation before generating the report.
        # (Set MOSAIC_MIROFISH_SKIP_START=1 to fall back to the old report-only path.)
        if not self._skip_start:
            self._start_simulation(simulation_id)
            self._poll_run_status(simulation_id)
        gen = self._post_json("/api/report/generate", {"simulation_id": simulation_id})
        self._poll_status("/api/report/generate/status", _dig(gen, "task_id"), simulation_id)
        report_id = self._report_id(simulation_id)
        rep = self._get_json(f"/api/report/{report_id}")
        md = _dig(rep, "markdown_content")
        if not isinstance(md, str):
            raise MiroFishUnavailable("report has no markdown_content")
        return md

    def _start_simulation(self, simulation_id: str) -> None:
        """Kick off the OASIS run (parallel platform), capped at ``max_rounds``."""
        # _max_rounds is always a positive int (resolved in __init__), so the cap
        # is always sent — a bad env value can't silently uncap the run.
        body: dict[str, Any] = {
            "simulation_id": simulation_id,
            "platform": "parallel",
            "max_rounds": self._max_rounds,
        }
        data = self._post_json("/api/simulation/start", body)
        if str(_dig(data, "runner_status") or "") == _RUN_FAILED:
            raise MiroFishUnavailable("simulation/start reported failure")

    def _poll_run_status(self, simulation_id: str) -> None:
        """Poll run-status until the run is completed/stopped (success) or failed."""
        deadline = time.monotonic() + self._poll_timeout
        while time.monotonic() < deadline:
            data = self._get_json(f"/api/simulation/{simulation_id}/run-status")
            status = str(_dig(data, "runner_status") or "")
            if status in _RUN_DONE:
                return
            if status == _RUN_FAILED:
                raise MiroFishUnavailable("simulation run failed")
            time.sleep(_POLL_INTERVAL)
        raise MiroFishUnavailable(f"simulation run timed out after {self._poll_timeout}s")

    def _ontology(self, seed_text: str, requirement: str) -> str:
        fields = {"simulation_requirement": requirement, "project_name": "mosaic"}
        files = {"files": ("seed.txt", seed_text.encode("utf-8"), "text/plain")}
        data = self._post_multipart("/api/graph/ontology/generate", fields, files)
        pid = _dig(data, "project_id")
        if not pid:
            raise MiroFishUnavailable("ontology/generate returned no project_id")
        return pid

    def _report_id(self, simulation_id: str) -> str:
        st = self._post_json(
            "/api/report/generate/status", {"simulation_id": simulation_id}
        )
        rid = _dig(st, "report_id")
        if not rid:
            raise MiroFishUnavailable("could not resolve report_id")
        return rid

    # ---- polling ---------------------------------------------------------

    def _poll(self, base_path: str, started: dict[str, Any], key: str, via_get: bool) -> None:
        task_id = _dig(started, key)
        if not task_id:
            return  # nothing to poll (already done)
        deadline = time.monotonic() + self._poll_timeout
        while time.monotonic() < deadline:
            data = self._get_json(f"{base_path}{task_id}") if via_get else {}
            status = str(_dig(data, "status") or "")
            if status in ("completed", "ready", "success"):
                return
            if status == "failed":
                raise MiroFishUnavailable(f"task {task_id} failed")
            time.sleep(_POLL_INTERVAL)
        raise MiroFishUnavailable(f"task {task_id} timed out after {self._poll_timeout}s")

    def _poll_status(self, path: str, task_id: Optional[str], simulation_id: str) -> None:
        deadline = time.monotonic() + self._poll_timeout
        while time.monotonic() < deadline:
            body = {"simulation_id": simulation_id}
            if task_id:
                body["task_id"] = task_id
            data = self._post_json(path, body)
            status = str(_dig(data, "status") or "")
            if status in ("completed", "ready", "success") or _dig(data, "already_prepared") or _dig(data, "already_completed"):
                return
            if status == "failed":
                raise MiroFishUnavailable(f"{path} reported failure")
            time.sleep(_POLL_INTERVAL)
        raise MiroFishUnavailable(f"{path} timed out after {self._poll_timeout}s")

    # ---- report → montecarlo-shaped scenario (lossy) ---------------------

    def _sentiment(self, md: str) -> float:
        low = md.lower()
        b = sum(low.count(w.lower()) for w in _BULL_WORDS)
        s = sum(low.count(w.lower()) for w in _BEAR_WORDS)
        if b + s == 0:
            return 0.0
        return max(-1.0, min(1.0, (b - s) / (b + s)))

    def _scenario(
        self, scenario_type: str, start: float, num_days: int, sentiment: float, md: str
    ) -> dict[str, Any]:
        # drift = scenario scaffold + report sentiment tilt
        drift = _SCENARIO_DRIFT.get(scenario_type, 0.0) + 0.05 * sentiment
        end = start * (1.0 + drift)
        prices = [round(start + (end - start) * i / max(num_days, 1), 4) for i in range(num_days + 1)]
        cum = end / start - 1.0
        regime = "RISK_ON" if cum > 0.10 else ("RISK_OFF" if cum < -0.10 else "NEUTRAL")
        return {
            "scenario_type": scenario_type,
            "scenario_name": f"OASIS {scenario_type}",
            "probability": _SCENARIO_PROB.get(scenario_type, 0.1),
            "num_days": num_days,
            "engine": "oasis",
            "price_paths": {
                _PROBE: {
                    "ticker": _PROBE,
                    "start_price": start,
                    "prices": prices,
                    "cumulative_return": round(cum, 4),
                    "volatility": round(abs(drift) * 2, 4),
                }
            },
            "events": [],
            "final_state": {
                "regime": regime,
                "narrative": (md[:200] if md else ""),
                "csi300_return": round(cum, 4),
                "report_sentiment": round(sentiment, 3),
            },
        }

    # ---- HTTP --------------------------------------------------------------

    def _get_json(self, path: str) -> Any:
        return self._request(urllib.request.Request(self._base_url + path, method="GET"))

    def _post_json(self, path: str, payload: dict[str, Any]) -> Any:
        req = urllib.request.Request(
            self._base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._request(req)

    def _post_multipart(self, path: str, fields: dict[str, str], files: dict) -> Any:
        boundary = uuid.uuid4().hex
        parts: list[bytes] = []
        for k, v in fields.items():
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
            )
        for k, (fname, content, ctype) in files.items():
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; "
                f"filename=\"{fname}\"\r\nContent-Type: {ctype}\r\n\r\n".encode()
            )
            parts.append(content if isinstance(content, bytes) else str(content).encode())
            parts.append(b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        req = urllib.request.Request(
            self._base_url + path,
            data=b"".join(parts),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        return self._request(req)

    def _request(self, req: urllib.request.Request) -> Any:
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                if not (200 <= resp.status < 300):
                    raise MiroFishUnavailable(f"MiroFish HTTP {resp.status} on {req.selector}")
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise MiroFishUnavailable(f"MiroFish HTTP {exc.code} on {req.selector}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise MiroFishUnavailable(f"MiroFish unreachable: {exc}") from exc
        except (ValueError, json.JSONDecodeError) as exc:
            raise MiroFishUnavailable(f"MiroFish invalid JSON: {exc}") from exc
        if isinstance(body, dict) and body.get("success") is False:
            raise MiroFishUnavailable(f"MiroFish error: {body.get('error')}")
        return body


def _dig(body: Any, key: str) -> Any:
    """The API wraps payloads as {success, data:{...}}; read key from data or top."""
    if not isinstance(body, dict):
        return None
    data = body.get("data")
    if isinstance(data, dict) and key in data:
        return data[key]
    return body.get(key)
