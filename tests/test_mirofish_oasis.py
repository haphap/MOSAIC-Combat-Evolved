"""Tests for the OASIS/MiroFish real-engine adapter (7M Step 3, multi-step API).

Verified against the real backend cloned to ~/Project/MiroFish: the pipeline is
ontology/generate → graph/build (poll) → simulation/create → prepare (poll) →
report/generate (poll) → GET report. Pure stdlib → deps-light. A fake
``urlopen`` routes by path; NO real network / service / keys are touched —
this validates request sequencing, polling, and report→scenario mapping only,
NOT a live integration (which needs LLM/Zep keys + cost).
"""

from __future__ import annotations

import importlib.util
import json
import os
import unittest
import urllib.error
from unittest.mock import patch

from mosaic.mirofish import oasis
from mosaic.mirofish.oasis import MiroFishUnavailable, OasisMiroFishEngine

_REPORT = "## A股前瞻\n整体偏利好,看多,预计反弹;警惕尾部下跌(利空)。\n"


class _Resp:
    def __init__(self, body, status=200):
        self._b = json.dumps(body).encode("utf-8")
        self.status = status

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _happy_router(report_md=_REPORT):
    """A fake urlopen that walks the full pipeline successfully."""
    calls = []

    def fake(req, timeout=None):
        p = req.selector
        calls.append((req.method, p))
        routes = {
            "/api/graph/ontology/generate": {"data": {"project_id": "proj_1"}},
            "/api/graph/build": {"data": {"task_id": "t_build"}},
            "/api/simulation/create": {"data": {"simulation_id": "sim_1"}},
            "/api/simulation/prepare": {"data": {"task_id": "t_prep"}},
            "/api/simulation/prepare/status": {"data": {"status": "completed"}},
            "/api/simulation/start": {"data": {"runner_status": "running"}},
            "/api/report/generate": {"data": {"task_id": "t_gen"}},
            "/api/report/generate/status": {"data": {"status": "completed", "report_id": "rep_1"}},
            "/api/report/rep_1": {"data": {"markdown_content": report_md, "outline": {}}},
        }
        if p.startswith("/api/graph/task/"):
            return _Resp({"data": {"status": "completed"}})
        if p.endswith("/run-status"):
            return _Resp({"success": True, "data": {"runner_status": "completed"}})
        if p in routes:
            return _Resp({"success": True, **routes[p]})
        return _Resp({"success": False, "error": f"unexpected {p}"}, status=404)

    return fake, calls


def _patch(fake):
    return patch.object(oasis.urllib.request, "urlopen", fake)


def _no_sleep():
    return patch.object(oasis.time, "sleep", lambda s: None)


class TestOasisMultiStep(unittest.TestCase):
    def test_no_url_raises(self):
        # explicitly unset so a repo .env (loaded by mosaic/__init__) can't leak a URL
        with patch.dict("os.environ", clear=False):
            os.environ.pop("MOSAIC_MIROFISH_URL", None)
            with self.assertRaises(MiroFishUnavailable) as ctx:
                OasisMiroFishEngine(base_url="").generate_all_scenarios(None, 5, 1, None)
        self.assertIn("MOSAIC_MIROFISH_URL", str(ctx.exception))

    def test_walks_full_pipeline_in_order(self):
        fake, calls = _happy_router()
        with _patch(fake), _no_sleep():
            out = OasisMiroFishEngine(base_url="http://x").generate_all_scenarios(
                {"000300.SH": 3500.0}, 5, 42, ["base", "bull"]
            )
        paths = [p for _, p in calls]
        # the real chain, in order
        self.assertEqual(paths[0], "/api/graph/ontology/generate")
        self.assertEqual(paths[1], "/api/graph/build")
        self.assertTrue(any(p.startswith("/api/graph/task/") for p in paths))
        self.assertIn("/api/simulation/create", paths)
        self.assertIn("/api/simulation/prepare", paths)
        # the OASIS run happens after prepare and before the report
        self.assertIn("/api/simulation/start", paths)
        self.assertTrue(any(p.endswith("/run-status") for p in paths))
        self.assertLess(paths.index("/api/simulation/prepare"), paths.index("/api/simulation/start"))
        self.assertLess(paths.index("/api/simulation/start"), paths.index("/api/report/generate"))
        self.assertIn("/api/report/generate", paths)
        self.assertEqual(paths[-1], "/api/report/rep_1")
        self.assertEqual(out[0]["engine"], "oasis")

    def test_report_sentiment_maps_to_regime(self):
        fake, _ = _happy_router()
        with _patch(fake), _no_sleep():
            out = OasisMiroFishEngine(base_url="http://x").generate_all_scenarios(
                {"000300.SH": 3500.0}, 5, 1, ["base", "bull", "tail_down"]
            )
        by = {s["scenario_type"]: s for s in out}
        self.assertGreater(by["base"]["final_state"]["report_sentiment"], 0)  # bullish report
        self.assertEqual(by["bull"]["final_state"]["regime"], "RISK_ON")
        self.assertEqual(by["tail_down"]["final_state"]["regime"], "RISK_OFF")

    def test_bearish_report_tilts_down(self):
        fake, _ = _happy_router(report_md="## 崩盘风险\n利空,看空,下跌,risk-off。\n")
        with _patch(fake), _no_sleep():
            out = OasisMiroFishEngine(base_url="http://x").generate_all_scenarios(None, 5, 1, ["base"])
        self.assertLess(out[0]["final_state"]["report_sentiment"], 0)

    def test_output_is_score_compatible(self):
        if importlib.util.find_spec("numpy") is None:
            self.skipTest("numpy not installed (.[data] extra)")
        from mosaic.mirofish import score_recommendation

        fake, _ = _happy_router()
        with _patch(fake), _no_sleep():
            out = OasisMiroFishEngine(base_url="http://x").generate_all_scenarios(None, 5, 1, ["bull"])
        score = score_recommendation(
            {"recommendation": "BUY", "tickers": ["000300.SH"], "conviction": 0.5}, out[0]
        )
        self.assertGreater(score, 0.5)

    def test_http_error_mid_pipeline_degrades(self):
        def fail(req, timeout=None):
            if req.selector == "/api/graph/ontology/generate":
                raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, None)
            return _Resp({"success": True, "data": {}})

        with _patch(fail), _no_sleep():
            with self.assertRaises(MiroFishUnavailable):
                OasisMiroFishEngine(base_url="http://x").generate_all_scenarios(None, 5, 1, None)

    def test_service_error_envelope_degrades(self):
        # {success: false} anywhere → MiroFishUnavailable (e.g. missing ZEP key on build)
        def fake(req, timeout=None):
            if req.selector == "/api/graph/ontology/generate":
                return _Resp({"success": True, "data": {"project_id": "p"}})
            return _Resp({"success": False, "error": "ZEP_API_KEY missing"})

        with _patch(fake), _no_sleep():
            with self.assertRaises(MiroFishUnavailable) as ctx:
                OasisMiroFishEngine(base_url="http://x").generate_all_scenarios(None, 5, 1, None)
        self.assertIn("ZEP", str(ctx.exception))

    def test_poll_timeout_degrades(self):
        def fake(req, timeout=None):
            p = req.selector
            if p == "/api/graph/ontology/generate":
                return _Resp({"data": {"project_id": "p"}})
            if p == "/api/graph/build":
                return _Resp({"data": {"task_id": "t"}})
            if p.startswith("/api/graph/task/"):
                return _Resp({"data": {"status": "processing"}})  # never completes
            return _Resp({"data": {}})

        eng = OasisMiroFishEngine(base_url="http://x", poll_timeout=0)
        with _patch(fake), _no_sleep():
            with self.assertRaises(MiroFishUnavailable) as ctx:
                eng.generate_all_scenarios(None, 5, 1, None)
        self.assertIn("timed out", str(ctx.exception))

    def test_seed_text_is_substantive(self):
        from mosaic.mirofish.oasis import _build_seed_text

        txt = _build_seed_text(42, 5, {"000300.SH": 3600.0})
        # names concrete A-share entities so the graph (and sim) has substance
        for kw in ("沪深300", "北向资金", "宁德时代", "券商", "510300"):
            self.assertIn(kw, txt)
        self.assertIn("3600", txt)  # CSI300 level threaded from start_prices
        self.assertIn("5", txt)     # num_days

    def test_env_var_default_url(self):
        with patch.dict("os.environ", {"MOSAIC_MIROFISH_URL": "http://env-host:5001"}):
            self.assertEqual(OasisMiroFishEngine()._base_url, "http://env-host:5001")

    def test_start_sends_max_rounds(self):
        fake, _ = _happy_router()
        bodies = {}

        def capture(req, timeout=None):
            if req.method == "POST" and req.data:
                try:  # ontology/generate is multipart, not JSON — skip it
                    bodies[req.selector] = json.loads(req.data.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    pass
            return fake(req, timeout)

        with _patch(capture), _no_sleep():
            OasisMiroFishEngine(base_url="http://x", max_rounds=3).generate_all_scenarios(
                None, 5, 1, ["base"]
            )
        self.assertEqual(bodies["/api/simulation/start"]["max_rounds"], 3)
        self.assertEqual(bodies["/api/simulation/start"]["simulation_id"], "sim_1")
        # graph-memory update must be on so the report reflects THIS run
        self.assertTrue(bodies["/api/simulation/start"]["enable_graph_memory_update"])

    def test_bad_env_max_rounds_falls_back_to_positive_cap(self):
        # 0 / negative / non-int env must NOT drop or corrupt the cap
        for bad in ("0", "-1", "abc", ""):
            with patch.dict("os.environ", {"MOSAIC_MIROFISH_MAX_ROUNDS": bad}):
                self.assertEqual(OasisMiroFishEngine(base_url="http://x")._max_rounds, 5)
        with patch.dict("os.environ", {"MOSAIC_MIROFISH_MAX_ROUNDS": "12"}):
            self.assertEqual(OasisMiroFishEngine(base_url="http://x")._max_rounds, 12)
        # explicit ctor 0 also clamps to the default (never uncapped)
        self.assertEqual(OasisMiroFishEngine(base_url="http://x", max_rounds=0)._max_rounds, 5)

    def test_start_always_sends_positive_cap(self):
        fake, _ = _happy_router()
        bodies = {}

        def capture(req, timeout=None):
            if req.method == "POST" and req.data:
                try:
                    bodies[req.selector] = json.loads(req.data.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    pass
            return fake(req, timeout)

        with patch.dict("os.environ", {"MOSAIC_MIROFISH_MAX_ROUNDS": "0"}):
            with _patch(capture), _no_sleep():
                OasisMiroFishEngine(base_url="http://x").generate_all_scenarios(None, 5, 1, ["base"])
        self.assertEqual(bodies["/api/simulation/start"]["max_rounds"], 5)

    def test_run_failed_degrades(self):
        def fake(req, timeout=None):
            p = req.selector
            if p.endswith("/run-status"):
                return _Resp({"success": True, "data": {"runner_status": "failed"}})
            base, _ = _happy_router()
            return base(req, timeout)

        with _patch(fake), _no_sleep():
            with self.assertRaises(MiroFishUnavailable) as ctx:
                OasisMiroFishEngine(base_url="http://x").generate_all_scenarios(None, 5, 1, None)
        self.assertIn("failed", str(ctx.exception))

    def test_run_stopped_aborts(self):
        # an externally stopped run is NOT a completed run → don't report on it
        def fake(req, timeout=None):
            if req.selector.endswith("/run-status"):
                return _Resp({"success": True, "data": {"runner_status": "stopped"}})
            base, _ = _happy_router()
            return base(req, timeout)

        with _patch(fake), _no_sleep():
            with self.assertRaises(MiroFishUnavailable) as ctx:
                OasisMiroFishEngine(base_url="http://x").generate_all_scenarios(None, 5, 1, None)
        self.assertIn("stopped", str(ctx.exception))

    def test_skip_start_env_does_report_only(self):
        fake, calls = _happy_router()
        with patch.dict("os.environ", {"MOSAIC_MIROFISH_SKIP_START": "1"}):
            with _patch(fake), _no_sleep():
                OasisMiroFishEngine(base_url="http://x").generate_all_scenarios(None, 5, 1, ["base"])
        paths = [p for _, p in calls]
        self.assertNotIn("/api/simulation/start", paths)
        self.assertFalse(any(p.endswith("/run-status") for p in paths))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
