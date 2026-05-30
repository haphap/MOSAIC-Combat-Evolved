"""Integration test for the ``mosaic.bridge`` JSON-RPC sidecar.

Drives the bridge as an external subprocess and never imports ``mosaic``
directly — proves the bridge is usable as an opaque black box from another
runtime (the Phase 1+ TypeScript CLI).

Two layers:

1. **Protocol contract** — 14 tests covering tools.* / config.* / cache.* /
   paper.* / backtest.* / parse-error / unknown-method shape. Hermetic; no
   network or vendor keys required.
2. **Macro-tool subprocess** — 5 tests covering tool registration, schema
   validation, vendor-unavailable error mapping, and backtest-mode blocking
   for the eight Layer-1 macro tools added on Day 4. Plus one live smoke
   case gated on ``TUSHARE_TOKEN``.

Tests that need real vendor data (Tushare / FRED / akshare) are skipped
unless the relevant token is set; that lets CI run hermetically while local
developers can flip the live tests on by exporting tokens.

Ported from ``etfagents/tests/test_bridge_protocol.py`` (Plan §11 0.5.1).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resolve_python() -> str:
    """Pick a Python interpreter for the bridge subprocess.

    Resolution order mirrors ``mosaic-ts/src/bridge/python.ts`` plus a CI-
    friendly fallback:

      1. ``$MOSAIC_PYTHON`` env var (explicit override; matches the TS client).
      2. ``<repo>/.venv/bin/python`` on POSIX, ``Scripts\\python.exe`` on Win.
      3. ``shutil.which("python3")`` — works on CI runners that don't have a
         project-local venv but do have ``python3`` on PATH.
      4. Fall back to ``sys.executable`` so the test always has *something*
         to run; logs the resolution to stderr for debuggability.

    The mosaic package itself must be importable from the chosen interpreter
    — CI configs should ``pip install -e ".[data,test]"`` ahead of running
    these tests when a project venv is unavailable.
    """
    env_path = os.environ.get("MOSAIC_PYTHON")
    if env_path:
        return env_path

    venv_posix = PROJECT_ROOT / ".venv" / "bin" / "python"
    venv_windows = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    for candidate in (venv_posix, venv_windows):
        if candidate.is_file():
            return str(candidate)

    which = shutil.which("python3") or shutil.which("python")
    if which:
        return which

    return sys.executable


PYTHON = _resolve_python()

# Expected count of tools.list entries on the Phase-0 Day-4 surface.
EXPECTED_MACRO_TOOLS = {
    "get_fred_series",
    "get_pboc_ops",
    "get_north_capital_flow",
    "get_lhb_ranking",
    "get_yield_curve_cn",
    "get_us_china_spread",
    "get_xueqiu_heat",
    "get_industry_policy",
}


class _BridgeTestCase(unittest.TestCase):
    """Spawn one bridge process per test for hermetic state."""

    def setUp(self) -> None:
        # Isolate cache/results to a tempdir so tests don't touch ~/.mosaic.
        self._tmp = tempfile.TemporaryDirectory()
        self._cache_dir = Path(self._tmp.name) / "cache"
        self._results_dir = Path(self._tmp.name) / "results"
        self._cache_dir.mkdir()
        self._results_dir.mkdir()
        self._paper_db = Path(self._tmp.name) / "paper_trading.db"

        env = {
            **os.environ,
            "MOSAIC_CACHE_DIR": str(self._cache_dir),
            "MOSAIC_RESULTS_DIR": str(self._results_dir),
            "PYTHONUNBUFFERED": "1",
        }
        self._proc = subprocess.Popen(
            [PYTHON, "-m", "mosaic.bridge"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(PROJECT_ROOT),
            env=env,
            text=True,
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        try:
            if self._proc.stdin and not self._proc.stdin.closed:
                self._proc.stdin.close()
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait(timeout=2)
        finally:
            for stream in (self._proc.stdout, self._proc.stderr):
                if stream is not None and not stream.closed:
                    stream.close()
            self._tmp.cleanup()

    # ------------------------------------------------------------ helpers

    def call(self, method: str, params: dict | None = None, *, req_id: int = 1) -> dict:
        msg: dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            msg["params"] = params
        assert self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(msg) + "\n")
        self._proc.stdin.flush()
        assert self._proc.stdout is not None
        line = self._proc.stdout.readline()
        if not line:
            stderr = ""
            if self._proc.stderr:
                stderr = self._proc.stderr.read()
            self.fail(f"Bridge closed stdout unexpectedly. stderr:\n{stderr}")
        return json.loads(line)

    def call_ok(self, method: str, params: dict | None = None, *, req_id: int = 1) -> object:
        response = self.call(method, params, req_id=req_id)
        self.assertNotIn(
            "error",
            response,
            msg=f"Expected success but got error: {response.get('error')}",
        )
        return response["result"]

    def call_err(self, method: str, params: dict | None = None, *, req_id: int = 1) -> dict:
        response = self.call(method, params, req_id=req_id)
        self.assertIn(
            "error",
            response,
            msg=f"Expected error but got result: {response.get('result')}",
        )
        return response["error"]


# ====================================================================
# Layer 1 — protocol contract (14 tests, hermetic)
# ====================================================================


class BridgeProtocolTests(_BridgeTestCase):
    # ------------------------------------------------------- tools.* tests

    def test_tools_list_returns_metadata_for_each_macro_tool(self) -> None:
        """tools.list must surface the 8 macro tools with name/description/schema.

        Phase 0 Day 4 lands exactly the macro_tools module. Phase 2+ will add
        more; assert ≥8 so this test stays green as the surface grows.
        """
        tools = self.call_ok("tools.list", {})
        self.assertIsInstance(tools, list)
        self.assertGreaterEqual(len(tools), 8, "expected ≥8 @tool functions on Phase 0")
        names = {t["name"] for t in tools}
        # Every macro tool must be present
        self.assertTrue(EXPECTED_MACRO_TOOLS.issubset(names))
        for tool in tools:
            self.assertIn("name", tool)
            self.assertIn("description", tool)
            self.assertIn("args_schema", tool)
            schema = tool["args_schema"]
            self.assertEqual(schema.get("type"), "object")
            self.assertIn("properties", schema)
            # Each tool's description is non-trivial
            self.assertGreater(len(tool["description"]), 20)

    def test_tools_call_unknown_name_returns_method_not_found(self) -> None:
        err = self.call_err("tools.call", {"name": "nonexistent_tool", "args": {}})
        self.assertEqual(err["code"], -32601)

    def test_tools_call_invalid_params_returns_invalid_params(self) -> None:
        err = self.call_err("tools.call", {"args": {}})  # missing 'name'
        self.assertEqual(err["code"], -32602)

    def test_tools_call_in_backtest_mode_blocks_unbounded_call(self) -> None:
        """Backtest-mode date-bounds must reject get_xueqiu_heat (no date arg).

        Proves the bridge wires the existing ``backtest_context`` correctly:
        ``_UNBOUNDED_BACKTEST_METHODS`` intercepts the call before the akshare
        side-effect runs.
        """
        err = self.call_err(
            "tools.call",
            {
                "name": "get_xueqiu_heat",
                "args": {"top_n": 5},
                "context": {"mode": "backtest", "as_of_date": "2020-06-01"},
            },
        )
        self.assertIn(err["code"], (-32001, -32003))
        self.assertIn("Backtest mode", err["message"])
        self.assertIn("get_xueqiu_heat", err["message"])

    # ------------------------------------------------------- config.* tests

    def test_config_default_get_set_round_trip(self) -> None:
        default = self.call_ok("config.default", {})
        self.assertIsInstance(default, dict)
        self.assertIn("data_vendors", default)
        self.assertIn("tool_vendors", default)
        # MOSAIC-specific keys (Plan §1)
        self.assertEqual(default["llm_provider"], "anthropic")
        self.assertEqual(default["output_language"], "Chinese")
        self.assertEqual(default["active_cohort"], "euphoria_2021")
        self.assertEqual(len(default["cohorts"]), 7)

        # Modify a key and push back
        modified = dict(default)
        modified["max_debate_rounds"] = 3
        applied = self.call_ok("config.set", {"config": modified})
        self.assertEqual(applied["max_debate_rounds"], 3)

        # config.get must reflect the change in this process
        live = self.call_ok("config.get", {})
        self.assertEqual(live["max_debate_rounds"], 3)

    def test_config_set_rejects_non_object(self) -> None:
        err = self.call_err("config.set", {"config": "not an object"})
        self.assertEqual(err["code"], -32602)

    # -------------------------------------------------------- cache.* tests

    def test_cache_stats_returns_per_category_breakdown(self) -> None:
        stats = self.call_ok("cache.stats", {})
        self.assertIsInstance(stats, dict)
        for category in ("api", "signals", "snapshots", "checkpoints"):
            self.assertIn(category, stats)
            self.assertIn("count", stats[category])
            self.assertIn("size_mb", stats[category])
        self.assertIn("total_mb", stats)

    def test_cache_cleanup_rejects_invalid_category(self) -> None:
        err = self.call_err("cache.cleanup", {"days": 30, "category": "bogus"})
        self.assertEqual(err["code"], -32602)

    # ----------------------------------------------------- paper.* tests
    #
    # The paper engine is ported (Phase 8 刀1): handlers reach a real
    # PaperTradingEngine. current_user works without a session ("default");
    # bad args still trip INVALID_PARAMS (-32602) before the engine is touched.

    def _paper_params(self, **extra) -> dict:
        return {"db_path": str(self._paper_db), **extra}

    def test_paper_current_user_defaults_without_session(self) -> None:
        result = self.call_ok("paper.current_user", self._paper_params())
        self.assertEqual(result["user"], "default")

    def test_paper_buy_invalid_quantity_rejected_before_engine(self) -> None:
        # Non-int quantity is rejected by param validation (no engine/network).
        err = self.call_err(
            "paper.buy",
            self._paper_params(ticker="510300.SH", quantity="100"),
        )
        self.assertEqual(err["code"], -32602)

    def test_paper_suggest_order_rejects_non_object_state(self) -> None:
        """Validation runs before the lazy paper-engine import."""
        err = self.call_err(
            "paper.suggest_order_from_signal",
            self._paper_params(ticker="510300.SH", state="not-a-dict"),
        )
        self.assertEqual(err["code"], -32602)

    # -------------------------------------------------- backtest.* tests
    #
    # backtest_run_candidate_pool validates the full payload BEFORE the lazy
    # import of mosaic.backtest, so even with the engine deferred to Phase 8
    # we still exercise the protocol contract here.

    def test_backtest_requires_tickers_and_signals(self) -> None:
        err = self.call_err(
            "backtest.run_candidate_pool",
            {"start_date": "2026-01-02", "end_date": "2026-01-31", "signals": {}},
        )
        self.assertEqual(err["code"], -32602)
        self.assertIn("tickers", err["message"])

        err = self.call_err(
            "backtest.run_candidate_pool",
            {
                "tickers": ["510300.SH"],
                "start_date": "2026-01-02",
                "end_date": "2026-01-31",
            },
        )
        self.assertEqual(err["code"], -32602)
        self.assertIn("signals", err["message"])

    # ------------------------------------------------- protocol-level

    def test_unknown_method_returns_method_not_found(self) -> None:
        err = self.call_err("does.not.exist", {})
        self.assertEqual(err["code"], -32601)

    def test_parse_error_does_not_kill_server(self) -> None:
        """Garbage input produces a parse-error response, not a crash."""
        assert self._proc.stdin is not None
        assert self._proc.stdout is not None
        self._proc.stdin.write("this is not json\n")
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        response = json.loads(line)
        self.assertEqual(response["error"]["code"], -32700)

        # Subsequent valid request still works
        result = self.call_ok("config.get", {}, req_id=99)
        self.assertIsInstance(result, dict)


# ====================================================================
# Layer 2 — macro-tool subprocess tests (5 hermetic + 1 live smoke)
# ====================================================================


class MacroToolBridgeTests(_BridgeTestCase):
    """End-to-end macro-tool tests over the JSON-RPC subprocess.

    These exercise the full path bridge → @tool wrapper → ``route_to_vendor``
    → underlying dataflow. Vendor calls without API keys are expected to
    fall through to ``DataVendorUnavailable`` / ``RuntimeError`` and surface
    as ``-32001 TOOL_EXECUTION_ERROR`` or ``-32003 DATA_VENDOR_UNAVAILABLE``.
    """

    def test_each_macro_tool_has_complete_args_schema(self) -> None:
        """Every Day-4 macro tool surfaces the expected fields."""
        tools = {t["name"]: t for t in self.call_ok("tools.list", {})}
        for name in EXPECTED_MACRO_TOOLS:
            self.assertIn(name, tools, f"missing {name}")
            schema = tools[name]["args_schema"]
            self.assertEqual(schema["type"], "object")
            for prop, prop_schema in schema["properties"].items():
                self.assertIn("description", prop_schema, f"{name}.{prop} missing description")
                self.assertTrue(
                    prop_schema["description"].strip(),
                    f"{name}.{prop} description is empty",
                )

    def test_get_fred_series_rejects_missing_required_args(self) -> None:
        """Pydantic v2 schema rejects missing required args before vendor call."""
        err = self.call_err(
            "tools.call",
            {"name": "get_fred_series", "args": {"series_id": "FEDFUNDS"}},
        )
        # langchain wraps the schema error -> tools_call wraps to TOOL_EXECUTION_ERROR
        self.assertEqual(err["code"], -32001)
        self.assertIn("ValidationError", err["message"])
        self.assertIn("start_date", err["message"])
        self.assertIn("end_date", err["message"])

    def test_get_pboc_ops_without_token_returns_clean_error(self) -> None:
        """Without TUSHARE_TOKEN the call must surface a clear vendor-unavailable
        error, not crash the bridge."""
        # Force the env var to be missing inside the bridge subprocess by
        # restarting it without TUSHARE_TOKEN.
        self.tearDown()
        self._tmp = tempfile.TemporaryDirectory()
        self._cache_dir = Path(self._tmp.name) / "cache"
        self._results_dir = Path(self._tmp.name) / "results"
        self._cache_dir.mkdir()
        self._results_dir.mkdir()

        env = {
            k: v for k, v in os.environ.items()
            if k not in ("TUSHARE_TOKEN", "TUSHARE_API_TOKEN", "TS_TOKEN")
        }
        # mosaic/__init__.py calls load_dotenv() at import; setting the keys
        # to empty strings rather than deleting them prevents that from
        # repopulating from a developer's local .env file (load_dotenv
        # default is override=False, so it won't replace an existing key).
        env.update(
            {
                "TUSHARE_TOKEN": "",
                "TUSHARE_API_TOKEN": "",
                "TS_TOKEN": "",
                "MOSAIC_CACHE_DIR": str(self._cache_dir),
                "MOSAIC_RESULTS_DIR": str(self._results_dir),
                "PYTHONUNBUFFERED": "1",
            }
        )
        self._proc = subprocess.Popen(
            [PYTHON, "-m", "mosaic.bridge"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(PROJECT_ROOT),
            env=env,
            text=True,
            encoding="utf-8",
        )

        err = self.call_err(
            "tools.call",
            {
                "name": "get_pboc_ops",
                "args": {"curr_date": "2024-06-30", "look_back_days": 7},
            },
        )
        # Either TOOL_EXECUTION_ERROR (RuntimeError from fallback exhaustion)
        # or DATA_VENDOR_UNAVAILABLE (raised directly by the vendor).
        self.assertIn(err["code"], (-32001, -32003))
        self.assertIn("TUSHARE_TOKEN", err["message"])

        # Bridge must still serve subsequent calls.
        result = self.call_ok("tools.list", {}, req_id=99)
        self.assertGreaterEqual(len(result), 8)

    def test_get_xueqiu_heat_blocked_in_backtest_mode(self) -> None:
        """``get_xueqiu_heat`` is in ``_UNBOUNDED_BACKTEST_METHODS`` — should be
        rejected before akshare is touched."""
        err = self.call_err(
            "tools.call",
            {
                "name": "get_xueqiu_heat",
                "args": {"top_n": 3},
                "context": {"mode": "backtest", "as_of_date": "2020-06-01"},
            },
        )
        self.assertIn(err["code"], (-32001, -32003))
        self.assertIn("Backtest mode", err["message"])

    def test_get_north_capital_flow_validates_date_format(self) -> None:
        """Bad ISO date in args is caught in the route_to_vendor layer."""
        err = self.call_err(
            "tools.call",
            {
                "name": "get_north_capital_flow",
                "args": {"start_date": "2024/06/01", "end_date": "2024-06-28"},
            },
        )
        # macro_data raises DataVendorUnavailable("YYYY-MM-DD") — bridge maps
        # to TOOL_EXECUTION_ERROR or DATA_VENDOR_UNAVAILABLE.
        self.assertIn(err["code"], (-32001, -32003))
        self.assertIn("YYYY-MM-DD", err["message"])

    # -------------------- live smoke (Plan §11 0.5.2) -------------------

    @unittest.skipUnless(
        os.getenv("TUSHARE_TOKEN")
        or os.getenv("TUSHARE_API_TOKEN")
        or os.getenv("TS_TOKEN"),
        "set TUSHARE_TOKEN to run the live get_north_capital_flow smoke test",
    )
    def test_get_north_capital_flow_live(self) -> None:
        """End-to-end: spawn bridge subprocess, fetch real Tushare HSGT flow data.

        Plan §11 0.5.2. Skipped on systems without a Tushare token; flip on by
        exporting ``TUSHARE_TOKEN``.
        """
        result = self.call_ok(
            "tools.call",
            {
                "name": "get_north_capital_flow",
                "args": {"start_date": "2024-06-03", "end_date": "2024-06-07"},
            },
        )
        self.assertIn("text", result)
        body = result["text"]
        # Header line is present regardless of whether rows came back.
        self.assertIn("沪深股通", body)
        self.assertIn("moneyflow_hsgt", body)
        # Either real rows or the empty-window note. Both prove the round trip.
        self.assertTrue(
            "north_money" in body or "No HSGT flow rows" in body,
            f"unexpected body:\n{body}",
        )


# ====================================================================
# Layer 3 — broken-pipe regression (Phase 0 hotfix 2026-05-29)
# ====================================================================


class BrokenPipeRegressionTests(unittest.TestCase):
    """Regression coverage for the BrokenPipeError noise the user hit when a
    downstream consumer in a shell pipeline died before reading the bridge's
    response.

    Before the fix: bridge wrote one response (fit in pipe buffer), saw EOF
    on stdin, returned cleanly — but Python's interpreter shutdown flushed
    stdout one more time, hitting the closed pipe and emitting an
    "Exception ignored in <_io.TextIOWrapper>" + BrokenPipeError traceback
    on stderr. After the fix: bridge proactively redirects stdout to
    /dev/null when it detects a broken pipe, so the interpreter's at-exit
    flush has nothing to write.
    """

    def test_consumer_crash_does_not_leak_traceback(self) -> None:
        """Consumer dies before reading any output → bridge exits 0, no traceback."""
        request = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools.list",
            "params": {},
        })
        # Pipeline: bridge writes a single response, then a consumer that
        # exits *before reading anything* closes its stdin pipe.
        cmd = (
            f"echo '{request}' | "
            f"{PYTHON} -m mosaic.bridge 2>/tmp/_mosaic_bridge_stderr.log | "
            f"{PYTHON} -c 'raise SystemExit(0)'"
        )
        subprocess.run(
            cmd, shell=True, capture_output=True, timeout=15, executable="/bin/bash"
        )
        # The pipeline exit status is the consumer's (raise SystemExit(0) → 0).
        # The interesting signal is on the bridge's stderr.
        with open("/tmp/_mosaic_bridge_stderr.log", "r", encoding="utf-8") as fh:
            bridge_stderr = fh.read()
        self.assertNotIn(
            "Traceback",
            bridge_stderr,
            msg=f"bridge leaked a traceback on broken pipe:\n{bridge_stderr}",
        )
        self.assertNotIn(
            "BrokenPipeError",
            bridge_stderr,
            msg=f"bridge leaked BrokenPipeError on stderr:\n{bridge_stderr}",
        )
        # The "ready" log line should still appear — proves the bridge actually started.
        self.assertIn("MOSAIC bridge ready", bridge_stderr)

    def test_consumer_exits_after_one_response_is_clean(self) -> None:
        """Healthy single-shot pipeline (consumer reads one response then exits)."""
        request = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools.list",
            "params": {},
        })
        cmd = (
            f"echo '{request}' | "
            f"{PYTHON} -m mosaic.bridge 2>/tmp/_mosaic_bridge_stderr.log"
        )
        result = subprocess.run(
            cmd, shell=True, capture_output=True, timeout=15, executable="/bin/bash"
        )
        self.assertEqual(result.returncode, 0)
        # stdout should contain a valid JSON-RPC response
        line = result.stdout.decode("utf-8").strip()
        response = json.loads(line)
        self.assertEqual(response["id"], 1)
        self.assertIsInstance(response["result"], list)
        with open("/tmp/_mosaic_bridge_stderr.log", "r", encoding="utf-8") as fh:
            bridge_stderr = fh.read()
        self.assertNotIn("Traceback", bridge_stderr)
        self.assertNotIn("BrokenPipeError", bridge_stderr)


if __name__ == "__main__":
    sys.exit(unittest.main())
