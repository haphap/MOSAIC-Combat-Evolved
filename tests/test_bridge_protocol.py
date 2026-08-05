"""Integration test for the ``mosaic.bridge`` JSON-RPC sidecar.

Drives the bridge as an external subprocess; fixture setup uses the local
deterministic calendar collector, while all assertions treat the bridge as an
opaque JSON-RPC sidecar from another runtime (the TypeScript CLI).

Two layers:

1. **Protocol contract** — tests covering capability-bound tools.* / config.* / cache.* /
   paper.* / backtest.* / parse-error / unknown-method shape. Hermetic; no
   network or vendor keys required.
2. **Capability subprocess** — tests covering pre-materialisation, the closed
   role tool list, zero-argument calls, one-use semantics, and termination.

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

from scripts.build_structured_smoke_fixtures import build_structured_smoke_fixtures


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resolve_python() -> str:
    """Pick a Python interpreter for the bridge subprocess.

    Resolution order mirrors ``mosaic-ts/src/bridge/python.ts`` plus a CI-
    friendly fallback:

      1. ``$MOSAIC_PYTHON`` env var (explicit override; matches the TS client).
      2. ``<repo>/.venv/bin/python`` on POSIX, ``Scripts\\python.exe`` on Win.
      3. ``sys.executable`` — matches the active pytest/``uv run`` environment.
      4. ``shutil.which("python3")`` — last-resort fallback for ad hoc runs.

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

    if sys.executable:
        return sys.executable

    which = shutil.which("python3") or shutil.which("python")
    if which:
        return which

    raise RuntimeError("No Python interpreter available for bridge subprocess tests")


PYTHON = _resolve_python()

EXPECTED_CHINA_TOOL = "get_china_macro_snapshot"
_SHARED_FIXTURE_TMP: tempfile.TemporaryDirectory[str] | None = None
_SHARED_FIXTURE_BINDINGS: dict[str, str] = {}


def setUpModule() -> None:
    global _SHARED_FIXTURE_TMP, _SHARED_FIXTURE_BINDINGS
    _SHARED_FIXTURE_TMP = tempfile.TemporaryDirectory()
    _SHARED_FIXTURE_BINDINGS = build_structured_smoke_fixtures(
        Path(_SHARED_FIXTURE_TMP.name) / "cache", "2024-06-30"
    )


def tearDownModule() -> None:
    global _SHARED_FIXTURE_TMP, _SHARED_FIXTURE_BINDINGS
    if _SHARED_FIXTURE_TMP is not None:
        _SHARED_FIXTURE_TMP.cleanup()
    _SHARED_FIXTURE_TMP = None
    _SHARED_FIXTURE_BINDINGS = {}


class _BridgeTestCase(unittest.TestCase):
    """Spawn one bridge process per test for hermetic state."""

    def setUp(self) -> None:
        # Isolate cache/results to a tempdir so tests don't touch ~/.mosaic.
        self._tmp = tempfile.TemporaryDirectory()
        self._results_dir = Path(self._tmp.name) / "results"
        self._results_dir.mkdir()
        self._paper_db = Path(self._tmp.name) / "paper_trading.db"
        self._config_file = Path(self._tmp.name) / "config.json"
        self.assertTrue(_SHARED_FIXTURE_BINDINGS)

        env = {
            **os.environ,
            **_SHARED_FIXTURE_BINDINGS,
            "MOSAIC_RESULTS_DIR": str(self._results_dir),
            "MOSAIC_CONFIG": str(self._config_file),
            "MOSAIC_AGENT_TOOL_LEDGER_PATH": str(
                Path(self._tmp.name) / "agent_tool_capabilities.sqlite3"
            ),
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

    def call_ok(
        self, method: str, params: dict | None = None, *, req_id: int = 1
    ) -> object:
        response = self.call(method, params, req_id=req_id)
        self.assertNotIn(
            "error",
            response,
            msg=f"Expected success but got error: {response.get('error')}",
        )
        return response["result"]

    def call_err(
        self, method: str, params: dict | None = None, *, req_id: int = 1
    ) -> dict:
        response = self.call(method, params, req_id=req_id)
        self.assertIn(
            "error",
            response,
            msg=f"Expected error but got result: {response.get('result')}",
        )
        return response["error"]

    def prepare_china(self) -> dict:
        prepared = self.call_ok(
            "tools.prepare_capability",
            {
                "graph_run_id": "graph-protocol-1",
                "run_slot_id": "slot-china-1",
                "run_id": "run-china-1",
                "node_id": "node-china-1",
                "agent_id": "china",
                "stage": "china",
                "as_of": "2024-06-30",
                "materialization_request_id": "materialize-china-protocol-1",
                "runtime_inputs": {},
                "candidate_scope": None,
                "ttl_seconds": 60,
            },
        )
        self.assertIsInstance(prepared, dict)
        return prepared

    def prepare_china_capability(self) -> dict:
        return self.prepare_china()["capability"]


# ====================================================================
# Layer 1 — protocol contract (14 tests, hermetic)
# ====================================================================


class BridgeProtocolTests(_BridgeTestCase):
    # ------------------------------------------------------- tools.* tests

    def test_tools_list_requires_signed_capability(self) -> None:
        err = self.call_err("tools.list", {})
        self.assertEqual(err["code"], -32602)
        self.assertIn("capability", err["message"])

    def test_tools_call_unknown_name_returns_method_not_found(self) -> None:
        capability = self.prepare_china_capability()
        err = self.call_err(
            "tools.call",
            {"capability": capability, "name": "nonexistent_tool", "args": {}},
        )
        self.assertEqual(err["code"], -32601)

    def test_tools_call_invalid_params_returns_invalid_params(self) -> None:
        err = self.call_err("tools.call", {"args": {}})  # missing 'name'
        self.assertEqual(err["code"], -32602)

    def test_unscoped_xueqiu_tool_is_not_model_callable(self) -> None:
        capability = self.prepare_china_capability()
        err = self.call_err(
            "tools.call",
            {
                "capability": capability,
                "name": "get_xueqiu_heat",
                "args": {},
            },
        )
        self.assertEqual(err["code"], -32601)
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

    def test_config_save_persists_to_file(self) -> None:
        default = self.call_ok("config.default", {})
        modified = dict(default)
        modified["output_language"] = "English"
        applied = self.call_ok("config.save", {"config": modified})
        self.assertEqual(applied["output_language"], "English")
        # The isolated config file (MOSAIC_CONFIG) now exists with the override.
        self.assertTrue(self._config_file.is_file())
        on_disk = json.loads(self._config_file.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["output_language"], "English")

    def test_config_save_rejects_non_object(self) -> None:
        err = self.call_err("config.save", {"config": 123})
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
# Layer 2 — capability-bound snapshot subprocess tests
# ====================================================================


class MacroToolBridgeTests(_BridgeTestCase):
    """End-to-end capability lifecycle over the JSON-RPC subprocess."""

    def test_role_capability_lists_only_one_zero_argument_snapshot(self) -> None:
        capability = self.prepare_china_capability()
        tools = self.call_ok("tools.list", {"capability": capability})
        self.assertEqual([tool["name"] for tool in tools], [EXPECTED_CHINA_TOOL])
        self.assertEqual(
            tools[0]["args_schema"],
            {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        )

    def test_snapshot_call_returns_pre_materialized_payload_once(self) -> None:
        capability = self.prepare_china_capability()
        result = self.call_ok(
            "tools.call",
            {"capability": capability, "name": EXPECTED_CHINA_TOOL, "args": {}},
        )
        payload = json.loads(result["text"])
        self.assertEqual(payload["role"], "china")
        self.assertEqual(payload["as_of_date"], "2024-06-30")
        self.assertEqual(len(payload["observations"]), 5)

        err = self.call_err(
            "tools.call",
            {"capability": capability, "name": EXPECTED_CHINA_TOOL, "args": {}},
        )
        self.assertEqual(err["code"], -32602)
        self.assertIn("already been used", err["message"])

    def test_snapshot_tool_rejects_model_arguments(self) -> None:
        capability = self.prepare_china_capability()
        err = self.call_err(
            "tools.call",
            {
                "capability": capability,
                "name": EXPECTED_CHINA_TOOL,
                "args": {"as_of": "2099-01-01"},
            },
        )
        self.assertEqual(err["code"], -32602)
        self.assertIn("no arguments", err["message"])

    def test_terminated_capability_fails_closed(self) -> None:
        capability = self.prepare_china_capability()
        self.assertEqual(
            self.call_ok(
                "tools.terminate_capability",
                {"capability": capability, "reason": "node_finished"},
            ),
            {"terminated": True},
        )
        err = self.call_err(
            "tools.list",
            {"capability": capability},
        )
        self.assertEqual(err["code"], -32602)
        self.assertIn("terminated", err["message"])

    def test_paired_capability_reuses_the_materialized_bundle(self) -> None:
        root = self.prepare_china()
        issued = self.call_ok(
            "tools.issue_capability",
            {
                "graph_run_id": "graph-protocol-1",
                "run_slot_id": "slot-china-candidate",
                "run_id": "run-china-candidate",
                "node_id": "node-china-candidate",
                "agent_id": "china",
                "stage": "china",
                "as_of": "2024-06-30",
                "snapshot_bundle_id": root["bundle"]["snapshot_bundle_id"],
                "snapshot_bundle_hash": root["bundle"]["snapshot_bundle_hash"],
            },
        )
        self.assertEqual(issued["bundle"], root["bundle"])
        self.assertNotEqual(
            issued["capability"]["manifest"]["capability_id"],
            root["capability"]["manifest"]["capability_id"],
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
        request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools.list",
                "params": {},
            }
        )
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
        request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools.list",
                "params": {},
            }
        )
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
        self.assertEqual(response["error"]["code"], -32602)
        with open("/tmp/_mosaic_bridge_stderr.log", "r", encoding="utf-8") as fh:
            bridge_stderr = fh.read()
        self.assertNotIn("Traceback", bridge_stderr)
        self.assertNotIn("BrokenPipeError", bridge_stderr)


if __name__ == "__main__":
    sys.exit(unittest.main())
