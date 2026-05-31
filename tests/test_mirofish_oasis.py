"""Tests for the OASIS/MiroFish real-engine HTTP adapter (7M Step 3).

Pure stdlib (urllib) → deps-light. Uses a fake ``urlopen`` so NO real network /
service is touched — this validates request construction, response mapping, and
failure modes only, NOT a real integration (no live service in this env).
"""

from __future__ import annotations

import importlib.util
import json
import unittest
import urllib.error
from unittest.mock import patch

from mosaic.mirofish import oasis
from mosaic.mirofish.oasis import MiroFishUnavailable, OasisMiroFishEngine

_GOOD_SCENARIO = {
    "scenario_type": "base",
    "scenario_name": "Base",
    "probability": 0.5,
    "num_days": 5,
    "price_paths": {
        "000300.SH": {
            "ticker": "000300.SH",
            "start_price": 3500.0,
            "prices": [3500.0, 3550.0],
            "cumulative_return": 0.014,
            "volatility": 0.2,
        }
    },
    "events": [],
    "final_state": {"regime": "NEUTRAL", "narrative": "x", "csi300_return": 0.014},
}


class _FakeResp:
    def __init__(self, body, status=200):
        self._b = json.dumps(body).encode("utf-8")
        self.status = status

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch_urlopen(fn):
    return patch.object(oasis.urllib.request, "urlopen", fn)


class TestOasisAdapter(unittest.TestCase):
    def test_no_url_raises(self):
        with self.assertRaises(MiroFishUnavailable) as ctx:
            OasisMiroFishEngine(base_url="").generate_all_scenarios(None, 30, 1, None)
        self.assertIn("MOSAIC_MIROFISH_URL", str(ctx.exception))

    def test_posts_payload_and_maps_response(self):
        captured = {}

        def fake(req, timeout=None):
            captured["url"] = req.full_url
            captured["method"] = req.method
            captured["body"] = json.loads(req.data)
            return _FakeResp({"scenarios": [dict(_GOOD_SCENARIO)]})

        with _patch_urlopen(fake):
            out = OasisMiroFishEngine(base_url="http://localhost:5001/").generate_all_scenarios(
                {"000300.SH": 3500.0}, 5, 42, ["base"]
            )
        self.assertEqual(captured["url"], "http://localhost:5001/scenarios")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["body"]["seed"], 42)
        self.assertEqual(captured["body"]["scenarios"], ["base"])
        self.assertEqual(out[0]["engine"], "oasis")  # stamped
        self.assertEqual(out[0]["scenario_type"], "base")

    def test_output_is_score_compatible(self):
        if importlib.util.find_spec("numpy") is None:
            self.skipTest("numpy not installed (.[data] extra)")
        with _patch_urlopen(lambda req, timeout=None: _FakeResp({"scenarios": [dict(_GOOD_SCENARIO)]})):
            out = OasisMiroFishEngine(base_url="http://x").generate_all_scenarios(None, 5, 1, ["base"])
        from mosaic.mirofish import score_recommendation

        score = score_recommendation(
            {"recommendation": "BUY", "tickers": ["000300.SH"], "conviction": 0.5}, out[0]
        )
        self.assertGreater(score, 0.5)  # +1.4% base path

    def test_http_error_degrades(self):
        def fail(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 503, "down", {}, None)

        with _patch_urlopen(fail):
            with self.assertRaises(MiroFishUnavailable) as ctx:
                OasisMiroFishEngine(base_url="http://x").generate_all_scenarios(None, 5, 1, None)
        self.assertIn("503", str(ctx.exception))

    def test_unreachable_degrades(self):
        def fail(req, timeout=None):
            raise urllib.error.URLError("connection refused")

        with _patch_urlopen(fail):
            with self.assertRaises(MiroFishUnavailable):
                OasisMiroFishEngine(base_url="http://x").generate_all_scenarios(None, 5, 1, None)

    def test_bad_shape_rejected(self):
        with _patch_urlopen(lambda req, timeout=None: _FakeResp({"scenarios": [{"foo": 1}]})):
            with self.assertRaises(MiroFishUnavailable) as ctx:
                OasisMiroFishEngine(base_url="http://x").generate_all_scenarios(None, 5, 1, None)
        self.assertIn("required keys", str(ctx.exception))

    def test_empty_scenarios_rejected(self):
        with _patch_urlopen(lambda req, timeout=None: _FakeResp({"scenarios": []})):
            with self.assertRaises(MiroFishUnavailable):
                OasisMiroFishEngine(base_url="http://x").generate_all_scenarios(None, 5, 1, None)

    def test_env_var_default_url(self):
        with patch.dict("os.environ", {"MOSAIC_MIROFISH_URL": "http://env-host:5001"}):
            eng = OasisMiroFishEngine()
            with _patch_urlopen(
                lambda req, timeout=None: (_ for _ in ()).throw(AssertionError(req.full_url))
            ):
                try:
                    eng.generate_all_scenarios(None, 5, 1, None)
                except AssertionError as e:
                    self.assertEqual(str(e), "http://env-host:5001/scenarios")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
