"""Tests for the MiroFish report → ReportSignal parser (P4).

Locks the fix for the original bug: a clearly bullish report (explicit RISK_ON +
``+1.2%~+2.8%``) that the old keyword net mapped to NEUTRAL/0. Pure stdlib.
"""

from __future__ import annotations

import unittest

from mosaic.mirofish.report_parser import ReportSignal, parse_report

# The actual narrative from a live run that the old mapper scored NEUTRAL/0.
_REAL = (
    "# A股五日市场情景推演预测报告：流动性驱动下的结构性回暖\n"
    "> 在稳健偏宽松货币政策与财政加码双轮驱动下，未来5个交易日沪深300将呈现温和上行"
    "（+1.2%~+2.8%）、风险偏好明确转向RISK_ON，但上涨动能集中于基建链与低波红利资产，"
    "尾部风险聚焦于部分高估值成长板块的再平衡压力。\n"
)


class TestReportParser(unittest.TestCase):
    def test_real_bullish_report_no_longer_neutral(self):
        sig = parse_report(_REAL)
        self.assertEqual(sig.direction, "bullish")
        self.assertEqual(sig.regime, "RISK_ON")
        self.assertGreater(sig.drift, 0)          # +1.2%~+2.8% → ~+0.02
        self.assertAlmostEqual(sig.drift, 0.02, places=2)
        self.assertGreater(sig.signed_score, 0)   # was 0.0 under the old mapper
        self.assertTrue(sig.tail_risks)           # tail-risk sentence extracted

    def test_explicit_risk_off_report(self):
        md = ("## 风险提示\n市场风险偏好明确转向RISK_OFF，沪深300预计下行2%~4%，"
              "避险情绪升温，看空券商与高估值成长。尾部风险：外部加息、地缘冲突。")
        sig = parse_report(md)
        self.assertEqual(sig.direction, "bearish")
        self.assertEqual(sig.regime, "RISK_OFF")
        self.assertLess(sig.drift, 0)
        self.assertLess(sig.signed_score, 0)
        self.assertIn("外部加息", sig.tail_risks)

    def test_neutral_report_caps_confidence(self):
        md = "## 区间震荡\n市场预计维持中性震荡格局，多空分歧明显，建议观望。"
        sig = parse_report(md)
        self.assertEqual(sig.direction, "neutral")
        self.assertEqual(sig.regime, "NEUTRAL")
        self.assertEqual(sig.drift, 0.0)
        self.assertLessEqual(sig.confidence, 0.5)

    def test_drift_is_clamped(self):
        sig = parse_report("沪深300将大幅上行 80%~120%。")
        self.assertLessEqual(sig.drift, 0.30)

    def test_empty_report_is_neutral(self):
        sig = parse_report("")
        self.assertEqual(sig.direction, "neutral")
        self.assertEqual(sig.drift, 0.0)
        self.assertEqual(sig.signed_score, 0.0)

    def test_signed_score_bounds(self):
        sig = parse_report(_REAL)
        self.assertGreaterEqual(sig.signed_score, -1.0)
        self.assertLessEqual(sig.signed_score, 1.0)
        self.assertIsInstance(sig, ReportSignal)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
