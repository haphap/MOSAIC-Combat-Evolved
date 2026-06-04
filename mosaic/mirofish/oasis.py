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

from mosaic.mirofish.report_parser import ReportSignal, parse_report

DEFAULT_TIMEOUT = 60       # per-request socket timeout
DEFAULT_POLL_TIMEOUT = 1800  # max seconds to wait for an async step (sim is slow)
_POLL_INTERVAL = 5
_DEFAULT_MAX_ROUNDS = 5     # keep sims short by default — full OASIS runs are slow + LLM-costly
# Normal completion — incl. max_rounds truncation (the runner sets COMPLETED).
_RUN_DONE = ("completed",)
# Externally stopped or errored → not a usable run; don't report on it as if done.
_RUN_ABORTED = ("stopped", "failed")


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


# The prediction ask handed to MiroFish (drives ontology + report focus).
_REQUIREMENT = (
    "推演未来约 {num_days} 个交易日 A 股（以沪深300为代表）的市场情景："
    "总体方向、风险偏好（RISK_ON / NEUTRAL / RISK_OFF）、关键利好催化与尾部风险。"
)


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def _build_seed_text(
    seed: Optional[int], num_days: int, start_prices: Optional[Mapping[str, float]] = None
) -> str:
    """Compose a substantive A-share market briefing for graph construction.

    MiroFish builds the simulated world from this seed, so a one-line prompt
    yields an empty graph (no entities → no agents). This synthetic briefing
    names concrete A-share entities (indices, flows, policy bodies, sectors,
    bellwether names) so the graph — and the resulting simulation — has substance.
    """
    csi = float((start_prices or {}).get(_PROBE, 3500.0))
    return (
        f"A股市场情景推演种子材料（seed={seed}，预测周期约 {num_days} 个交易日；"
        f"沪深300当前约 {csi:.0f} 点）。\n\n"
        "【宏观与政策】中国人民银行实施稳健偏宽松的货币政策，市场预期可能降准或下调LPR以释放"
        "流动性；财政部加大基建与消费刺激。中美利差、人民币汇率以及美联储利率路径是主要外部"
        "风险变量。\n\n"
        "【资金面】主力资金流向与行业资金流是重要风向标；沪深股通成交活跃名单与外资持股变化"
        "反映外资态度。资金在贵州茅台、宁德时代、招商银行等权重股之间轮动；两融余额与成交量"
        "反映市场风险偏好。\n\n"
        "【板块与指数】核心基准为沪深300、上证综指、创业板指；主要轮动板块包括券商、银行、白酒、"
        "新能源（光伏与锂电）、半导体、医药；宽基ETF（如510300、510050）承接配置资金。\n\n"
        "【风险与催化】需评估市场处于风险偏好上行、中性还是避险，并识别尾部风险（外部加息、"
        "地缘冲突、监管收紧）与利好催化（政策宽松、企业盈利超预期）。\n"
    )

# A-share scenario scaffold reused for the montecarlo-shaped output.
_PROBE = "000300.SH"
_SCENARIO_PROB = {"base": 0.5, "bull": 0.2, "bear": 0.2, "tail_up": 0.05, "tail_down": 0.05}
_SCENARIO_DRIFT = {"base": 0.0, "bull": 0.10, "bear": -0.10, "tail_up": 0.25, "tail_down": -0.25}


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
        self._llm_base_url = _first_env("MOSAIC_MIROFISH_LLM_BASE_URL", "LLM_BASE_URL", "OPENAI_BASE_URL")
        self._llm_api_key = _first_env("MOSAIC_MIROFISH_LLM_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY")
        self._llm_model = _first_env("MOSAIC_MIROFISH_LLM_MODEL", "LLM_MODEL")
        self._embedding_base_url = _first_env(
            "MOSAIC_MIROFISH_EMBEDDING_BASE_URL",
            "EMBEDDING_BASE_URL",
            "DASHSCOPE_BASE_URL",
        )
        self._embedding_api_key = _first_env(
            "MOSAIC_MIROFISH_EMBEDDING_API_KEY",
            "EMBEDDING_API_KEY",
            "DASHSCOPE_API_KEY",
        )
        self._embedding_model = _first_env("MOSAIC_MIROFISH_EMBEDDING_MODEL", "EMBEDDING_MODEL")

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
        report_md = self._run_pipeline(seed, num_days, start_prices)
        signal = parse_report(report_md)  # structured direction/regime/drift/tails
        start = float((start_prices or {}).get(_PROBE, 3500.0))
        types = scenarios or ["base", "bull", "bear", "tail_up", "tail_down"]
        return [self._scenario(t, start, num_days, signal, report_md) for t in types]

    # ---- real multi-step pipeline ----------------------------------------

    def _run_pipeline(
        self,
        seed: Optional[int],
        num_days: int = 30,
        start_prices: Optional[Mapping[str, float]] = None,
    ) -> str:
        requirement = _REQUIREMENT.format(num_days=num_days)
        seed_text = _build_seed_text(seed, num_days, start_prices)
        project_id = self._ontology(seed_text, requirement)
        self._build_graph(project_id)
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
        gen = self._post_json(
            "/api/report/generate",
            self._with_model_configs({"simulation_id": simulation_id}),
        )
        self._poll_status("/api/report/generate/status", _dig(gen, "task_id"), simulation_id)
        report_id = self._report_id(simulation_id)
        rep = self._get_json(f"/api/report/{report_id}")
        md = _dig(rep, "markdown_content")
        if not isinstance(md, str):
            raise MiroFishUnavailable("report has no markdown_content")
        return md

    def _build_graph(self, project_id: str) -> None:
        """Build graph; retry once if extraction completes with zero nodes."""
        for attempt in range(2):
            payload = self._with_model_configs({"project_id": project_id})
            if attempt > 0:
                payload["force"] = True
            result = self._poll(
                "/api/graph/task/",
                self._post_json("/api/graph/build", payload),
                key="task_id",
                via_get=True,
            )
            node_count = _task_result_value(result, "node_count")
            if node_count is None:
                return
            if _safe_int(node_count, 0) > 0:
                return
        raise MiroFishUnavailable("graph build completed with zero nodes after retry")

    def _start_simulation(self, simulation_id: str) -> None:
        """Kick off the OASIS run (parallel platform), capped at ``max_rounds``."""
        # _max_rounds is always a positive int (resolved in __init__), so the cap
        # is always sent — a bad env value can't silently uncap the run.
        body: dict[str, Any] = {
            "simulation_id": simulation_id,
            "platform": "parallel",
            "max_rounds": self._max_rounds,
            # Stream agent activity into graph memory so the report reflects THIS
            # run — ReportAgent reads the graph, not actions.jsonl. Without this the
            # report is built from mostly pre-run graph state.
            "enable_graph_memory_update": True,
        }
        llm_config = self._llm_config_payload()
        if llm_config:
            body["llm_config"] = llm_config
        embedding_config = self._embedding_config_payload()
        if embedding_config:
            body["embedding_config"] = embedding_config
        data = self._post_json("/api/simulation/start", body)
        if str(_dig(data, "runner_status") or "") in _RUN_ABORTED:
            raise MiroFishUnavailable("simulation/start reported failure")

    def _llm_config_payload(self) -> dict[str, str]:
        payload: dict[str, str] = {}
        if self._llm_base_url:
            payload["base_url"] = self._llm_base_url
        if self._llm_api_key:
            payload["api_key"] = self._llm_api_key
        if self._llm_model:
            payload["model"] = self._llm_model
        return payload

    def _embedding_config_payload(self) -> dict[str, str]:
        payload: dict[str, str] = {}
        if self._embedding_base_url:
            payload["base_url"] = self._embedding_base_url
        if self._embedding_api_key:
            payload["api_key"] = self._embedding_api_key
        if self._embedding_model:
            payload["model"] = self._embedding_model
        return payload

    def _with_model_configs(self, payload: dict[str, Any]) -> dict[str, Any]:
        llm_config = self._llm_config_payload()
        if llm_config:
            payload["llm_config"] = llm_config
        embedding_config = self._embedding_config_payload()
        if embedding_config:
            payload["embedding_config"] = embedding_config
        return payload

    def _poll_run_status(self, simulation_id: str) -> None:
        """Poll run-status until the run completes; raise if it's aborted/stopped/failed."""
        deadline = time.monotonic() + self._poll_timeout
        while time.monotonic() < deadline:
            data = self._get_json(f"/api/simulation/{simulation_id}/run-status")
            status = str(_dig(data, "runner_status") or "")
            if status in _RUN_DONE:
                return
            if status in _RUN_ABORTED:
                raise MiroFishUnavailable(f"simulation run {status} before completion")
            time.sleep(_POLL_INTERVAL)
        raise MiroFishUnavailable(f"simulation run timed out after {self._poll_timeout}s")

    def _ontology(self, seed_text: str, requirement: str) -> str:
        fields = {"simulation_requirement": requirement, "project_name": "mosaic"}
        llm_config = self._llm_config_payload()
        if llm_config:
            fields["llm_config"] = json.dumps(llm_config, ensure_ascii=False)
        embedding_config = self._embedding_config_payload()
        if embedding_config:
            fields["embedding_config"] = json.dumps(embedding_config, ensure_ascii=False)
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

    def _poll(self, base_path: str, started: dict[str, Any], key: str, via_get: bool) -> dict[str, Any]:
        task_id = _dig(started, key)
        if not task_id:
            return started  # nothing to poll (already done)
        deadline = time.monotonic() + self._poll_timeout
        while time.monotonic() < deadline:
            data = self._get_json(f"{base_path}{task_id}") if via_get else {}
            status = str(_dig(data, "status") or "")
            if status in ("completed", "ready", "success"):
                return data
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

    def _scenario(
        self, scenario_type: str, start: float, num_days: int, signal: ReportSignal, md: str
    ) -> dict[str, Any]:
        # base case = the report's own directional view; bull/bear/tail = stress
        # scaffolds lightly tilted by the report's drift.
        if scenario_type == "base":
            drift = signal.drift
            regime = signal.regime
        else:
            drift = _SCENARIO_DRIFT.get(scenario_type, 0.0) + 0.3 * signal.drift
            regime = "RISK_ON" if drift > 0.02 else ("RISK_OFF" if drift < -0.02 else "NEUTRAL")
        end = start * (1.0 + drift)
        prices = [round(start + (end - start) * i / max(num_days, 1), 4) for i in range(num_days + 1)]
        cum = end / start - 1.0
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
                "narrative": signal.summary or (md[:200] if md else ""),
                "csi300_return": round(cum, 4),
                # structured report signal (lossy: narrative → directional view, not OHLCV)
                "report_direction": signal.direction,
                "report_confidence": signal.confidence,
                "report_regime": signal.regime,
                "report_sentiment": signal.signed_score,  # back-compat scalar
                "tail_risks": signal.tail_risks,
                "mapping_lossy": True,
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


def _task_result_value(body: Any, key: str) -> Any:
    """Read a field from MiroFish task ``data.result`` if present."""
    if not isinstance(body, dict):
        return None
    data = body.get("data")
    if not isinstance(data, dict):
        return None
    result = data.get("result")
    if isinstance(result, dict):
        return result.get(key)
    return None
