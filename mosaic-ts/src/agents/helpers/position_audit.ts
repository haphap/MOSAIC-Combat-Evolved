import type { CurrentPositionsSnapshot } from "../types.js";

export function buildPositionAuditToolStatusSummary(
  snapshot: CurrentPositionsSnapshot,
): Record<string, string> {
  const status = snapshot.snapshot_status;
  const summary: Record<string, string> = {};
  switch (snapshot.position_source) {
    case "paper_account":
      summary["paper.get_account"] = status === "missing" ? "source_error" : "called";
      summary["paper.get_positions"] = status === "missing" ? "source_error" : "called";
      break;
    case "backtest_replay":
      summary["backtest.position_replay"] = status;
      break;
    case "cli_fixture":
      summary["cli.current_positions_fixture"] = status;
      break;
    case "empty_confirmed":
      summary.current_positions = "empty_confirmed";
      break;
    case "unknown":
      summary.current_positions = status;
      break;
  }
  summary.market_prices =
    status === "missing" ? "missing" : snapshot.positions.length > 0 ? "loaded" : "empty_scope";
  return summary;
}
