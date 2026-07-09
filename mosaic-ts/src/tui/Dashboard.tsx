/**
 * Phase 10: Ink dashboard. Aggregates existing read RPCs into one screen.
 * Tabs: 1 Today (latest CIO picks) / 2 WinRate (per-ticker hit rate) / 3 Skill /
 * 4 Paper / 5 Cohorts / 6 MiroFish (scenario context + recent runs) /
 * 7 Settings (curated, editable, persisted config via config.save); r=refresh
 * (manual; no auto-poll), q=quit. The BridgeApi is injected so it is testable.
 */

import { Box, Text, useApp, useInput } from "ink";
import { useCallback, useEffect, useRef, useState } from "react";
import type {
  BacktestActionSummary,
  BacktestRunInfo,
  BridgeApi,
  CioAction,
  CioActions,
  CohortInfo,
  MirofishContext,
  MirofishHistoryEntry,
  MosaicConfig,
  PaperAccount,
  PaperPosition,
  PaperTrade,
  SkillRow,
  WinRateRow,
} from "../bridge/types.js";

type Tab = "today" | "winrate" | "skill" | "paper" | "cohorts" | "mirofish" | "settings";
const TABS: Tab[] = ["today", "winrate", "skill", "paper", "cohorts", "mirofish", "settings"];

interface Props {
  api: Pick<
    BridgeApi,
    | "scorecardLatestCioActions"
    | "scorecardWinRate"
    | "scorecardListSkill"
    | "paperGetAccount"
    | "paperGetPositions"
    | "paperGetTrades"
    | "backtestActionSummary"
    | "backtestListRuns"
    | "prismListCohorts"
    | "mirofishGetContext"
    | "mirofishGetHistory"
    | "configGet"
    | "configDefault"
    | "configSave"
  >;
  cohort: string;
  user?: string;
}

interface Data {
  today: CioActions;
  winrate: WinRateRow[];
  skill: SkillRow[];
  account: PaperAccount | null;
  positions: PaperPosition[];
  trades: PaperTrade[];
  backtestRuns: BacktestRunInfo[];
  backtestSummaries: BacktestActionSummary[];
  cohorts: CohortInfo[];
  mirofishContext: MirofishContext | null;
  mirofishRuns: MirofishHistoryEntry[];
}

export function Dashboard({ api, cohort, user }: Props) {
  const { exit } = useApp();
  const [tab, setTab] = useState<Tab>("today");
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [settingsEditing, setSettingsEditing] = useState(false);
  const mounted = useRef(true);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [today, winrate, skill, account, positions, trades, backtestRuns, cohorts] =
        await Promise.all([
          api.scorecardLatestCioActions(cohort),
          api.scorecardWinRate(cohort).then((r) => r.rows),
          api.scorecardListSkill(cohort).then((r) => r.rows),
          api.paperGetAccount(user ? { user_id: user } : {}).catch(() => null),
          api.paperGetPositions(user ? { user_id: user } : {}).catch(() => []),
          api.paperGetTrades(user ? { user_id: user, limit: 30 } : { limit: 30 }).catch(() => []),
          api
            .backtestListRuns({ cohort })
            .then((r) => r.runs)
            .catch(() => []),
          api.prismListCohorts().then((r) => r.cohorts),
        ]);
      const mirofishContext = await api
        .mirofishGetContext()
        .then((r) => r.context)
        .catch(() => null);
      const mirofishRuns = await api
        .mirofishGetHistory({ days: 10 })
        .then((r) => r.history)
        .catch(() => []);
      const backtestSummaries = await Promise.all(
        backtestRuns.slice(0, 5).map((run) => api.backtestActionSummary(run.id).catch(() => null)),
      ).then((items) => items.filter((item): item is BacktestActionSummary => item !== null));
      if (mounted.current)
        setData({
          today,
          winrate,
          skill,
          account,
          positions,
          trades,
          backtestRuns,
          backtestSummaries,
          cohorts,
          mirofishContext,
          mirofishRuns,
        });
    } catch (err) {
      if (mounted.current) setError((err as Error).message);
    }
  }, [api, cohort, user]);

  useEffect(() => {
    void load();
    return () => {
      mounted.current = false;
    };
  }, [load]);

  useInput((input) => {
    // When the settings tab is in edit mode, it owns all keystrokes.
    if (settingsEditing) return;
    if (input === "q") exit();
    else if (input === "r") void load();
    else if (input === "1") setTab("today");
    else if (input === "2") setTab("winrate");
    else if (input === "3") setTab("skill");
    else if (input === "4") setTab("paper");
    else if (input === "5") setTab("cohorts");
    else if (input === "6") setTab("mirofish");
    else if (input === "7") setTab("settings");
  });

  return (
    <Box flexDirection="column">
      <Box>
        {TABS.map((t, i) => (
          <Text key={t} bold={tab === t} color={tab === t ? "cyan" : "gray"}>
            {` ${i + 1} ${t} `}
          </Text>
        ))}
      </Box>
      <Box marginTop={1} flexDirection="column">
        {error ? (
          <Text color="red">error: {error}</Text>
        ) : tab === "settings" ? (
          <SettingsTab api={api} onEditingChange={setSettingsEditing} />
        ) : !data ? (
          <Text color="yellow">loading…</Text>
        ) : tab === "today" ? (
          <TodayTab today={data.today} account={data.account} positions={data.positions} />
        ) : tab === "winrate" ? (
          <WinRateTab rows={data.winrate} cohort={cohort} />
        ) : tab === "skill" ? (
          <SkillTab rows={data.skill} cohort={cohort} />
        ) : tab === "paper" ? (
          <PaperTab
            account={data.account}
            positions={data.positions}
            trades={data.trades}
            today={data.today}
            backtestRuns={data.backtestRuns}
            backtestSummaries={data.backtestSummaries}
          />
        ) : tab === "cohorts" ? (
          <CohortsTab cohorts={data.cohorts} />
        ) : (
          <MirofishTab context={data.mirofishContext} runs={data.mirofishRuns} />
        )}
      </Box>
      <Box marginTop={1}>
        <Text dimColor>[1-7] switch · [r] refresh · [q] quit · cohort={cohort}</Text>
      </Box>
    </Box>
  );
}

function TodayTab({
  today,
  account,
  positions,
}: {
  today: CioActions;
  account: PaperAccount | null;
  positions: PaperPosition[];
}) {
  if (!today.date || today.actions.length === 0)
    return <Text dimColor>no CIO recommendations yet — run a daily cycle first</Text>;
  const targetByTicker = new Map(today.actions.map((action) => [action.ticker, action]));
  const currentWeights = currentPaperWeights(account, positions);
  const rows = today.actions.map((action) => actionDisplay(action, currentWeights));
  const persistedLoaded = today.actions.filter(
    (action) => action.current_weight_pct != null,
  ).length;
  const reviewed = Math.max(
    positions.filter((position) => targetByTicker.has(position.ticker)).length,
    today.actions.filter((action) => action.position_decision != null).length,
  );
  const loaded = Math.max(positions.length, persistedLoaded);
  const staleCount = rows.filter(
    (row) => row.riskFlags.includes("stale_thesis") || row.thesisStatus === "expired",
  ).length;
  const agentAuditSummary = formatDecisionAgentAudits(today.actions);
  const stopLossOverrideCount = rows.filter(
    (row) =>
      row.riskFlags.includes("stop_loss_breached") &&
      (row.positionDecision === "HOLD" || row.positionDecision === "ADD"),
  ).length;
  const driftCount = rows.filter((row) => Math.abs(row.deltaWeightPct) > 1).length;
  const warnings: string[] = [];
  if (account === null) warnings.push("MISSING_POSITION_SNAPSHOT");
  if (positions.some((position) => !targetByTicker.has(position.ticker))) {
    warnings.push("UNREVIEWED_POSITION");
  }
  if (positions.some((position) => isPositionStale(position, today.date))) {
    warnings.push("POSITION_DATA_STALE");
  }
  if (stopLossOverrideCount > 0) warnings.push("STOP_LOSS_OVERRIDE");
  if (staleCount > 0) warnings.push("STALE_THESIS");
  if (rows.some((row) => row.targetWeightPct > 25)) warnings.push("TARGET_WEIGHT_OVER_LIMIT");
  if (driftCount > 0) warnings.push("TARGET_CURRENT_DRIFT");
  return (
    <Box flexDirection="column">
      <Text color="cyan">
        {`today's CIO plan (${today.date})   ticker      action  pos     current% target% delta% thesis   flags / dissent`}
      </Text>
      <Text dimColor>
        {`positions loaded ${loaded} reviewed ${reviewed}/${loaded} stale ${staleCount} ` +
          `stop_loss_overrides ${stopLossOverrideCount} drift ${driftCount}` +
          (warnings.length > 0 ? `  warnings=${warnings.join(",")}` : "")}
      </Text>
      {agentAuditSummary ? <Text dimColor>{agentAuditSummary}</Text> : null}
      {rows.map((row) => (
        <Text key={row.ticker}>
          {row.ticker.padEnd(11)} {row.action.padEnd(6)} {row.positionDecision.padEnd(7)}{" "}
          {row.currentWeightPct.toFixed(1).padStart(8)} {row.targetWeightPct.toFixed(1).padStart(7)}{" "}
          {row.deltaWeightPct.toFixed(1).padStart(6)} {row.thesisStatus.padEnd(8)}{" "}
          {formatFlagsAndNotes(row)}
        </Text>
      ))}
    </Box>
  );
}

function WinRateTab({ rows, cohort }: { rows: WinRateRow[]; cohort: string }) {
  if (rows.length === 0)
    return <Text dimColor>no scored picks yet for {cohort} (need forward returns)</Text>;
  return (
    <Box flexDirection="column">
      <Text color="cyan">{`ticker      win_rate   n   avg_dir_ret_5d`}</Text>
      {rows.slice(0, 15).map((r) => (
        <Text key={r.ticker} color={r.win_rate >= 0.5 ? "green" : "red"}>
          {r.ticker.padEnd(11)} {(r.win_rate * 100).toFixed(1).padStart(6)}%{" "}
          {String(r.n).padStart(4)} {(r.avg_dir_return_5d * 100).toFixed(2)}%
        </Text>
      ))}
    </Box>
  );
}

function SkillTab({ rows, cohort }: { rows: SkillRow[]; cohort: string }) {
  if (rows.length === 0) return <Text dimColor>no scored agents for {cohort}</Text>;
  return (
    <Box flexDirection="column">
      <Text color="cyan">{`agent              alpha_5d   sharpe    n`}</Text>
      {rows.slice(0, 12).map((r) => (
        <Text key={r.agent}>
          {r.agent.padEnd(18)} {fmt(r.mean_alpha_5d)} {fmt(r.sharpe_window).padStart(8)}{" "}
          {String(r.n_obs).padStart(4)}
        </Text>
      ))}
    </Box>
  );
}

function PaperTab({
  account,
  positions,
  trades,
  today,
  backtestRuns,
  backtestSummaries,
}: {
  account: PaperAccount | null;
  positions: PaperPosition[];
  trades: PaperTrade[];
  today: CioActions;
  backtestRuns: BacktestRunInfo[];
  backtestSummaries: BacktestActionSummary[];
}) {
  if (!account) return <Text dimColor>no paper account (login first)</Text>;
  const currentWeights = currentPaperWeights(account, positions);
  const actionRows = today.actions.map((action) => actionDisplay(action, currentWeights));
  const latestTradeByTicker = latestTradeMap(trades);
  return (
    <Box flexDirection="column">
      <Text>
        {`cash ${account.cash.toFixed(2)}  market ${account.market_value.toFixed(2)}  total ${account.total_assets.toFixed(2)}`}
      </Text>
      <Text
        dimColor
      >{`realized ${account.realized_pnl.toFixed(2)}  unrealized ${account.unrealized_pnl.toFixed(2)}`}</Text>
      {positions.length === 0 ? (
        <Text dimColor>no positions</Text>
      ) : (
        positions.slice(0, 10).map((p) => (
          <Text key={p.ticker}>
            {p.ticker.padEnd(11)} qty {String(p.quantity).padStart(6)} weight%{" "}
            {((p.market_value / Math.max(account.total_assets, 1)) * 100).toFixed(1)} pnl%{" "}
            {p.pnl_pct.toFixed(2)}
          </Text>
        ))
      )}
      <Box marginTop={1} flexDirection="column">
        <Text color="cyan">paper target-delta execution</Text>
        {actionRows.length === 0 ? (
          <Text dimColor>no target actions</Text>
        ) : (
          actionRows
            .slice(0, 10)
            .map((row) => (
              <PaperExecutionRow
                key={row.ticker}
                row={row}
                latestTrade={latestTradeByTicker.get(row.ticker)}
              />
            ))
        )}
      </Box>
      <Box marginTop={1} flexDirection="column">
        <Text color="cyan">recent backtest carry-over</Text>
        {backtestRuns.length === 0 ? (
          <Text dimColor>no backtest runs</Text>
        ) : (
          backtestRuns
            .slice(0, 5)
            .map((run) => (
              <BacktestCarryOverRow
                key={run.id}
                run={run}
                summary={backtestSummaries.find((item) => item.run_id === run.id)}
              />
            ))
        )}
      </Box>
    </Box>
  );
}

function BacktestCarryOverRow({
  run,
  summary,
}: {
  run: BacktestRunInfo;
  summary: BacktestActionSummary | undefined;
}) {
  const tradeDays = summary?.trade_day_count ?? run.distinct_trade_days ?? 0;
  const actionCount = summary?.action_count ?? run.action_count ?? 0;
  const actionMix = summary
    ? `buy=${summary.action_counts.BUY ?? 0} reduce=${summary.action_counts.REDUCE ?? 0} exit=${
        summary.action_counts.SELL ?? 0
      }`
    : "buy=- reduce=- exit=-";
  return (
    <Box flexDirection="column">
      <Text>
        #{String(run.id).padEnd(4)} {run.cohort.padEnd(16)} {run.start_date}..{run.end_date}{" "}
        trade_days {String(tradeDays).padStart(3)} actions {String(actionCount).padStart(3)}{" "}
        {run.completed_at ? "complete" : "open"}
      </Text>
      <Text>
        {" ".repeat(6)} turnover_proxy {formatNumberOrDash(summary?.turnover_proxy)} hold_days{" "}
        {String(summary?.max_observed_holding_days ?? "-").padStart(3)} stale_thesis{" "}
        {String(summary?.stale_thesis_proxy_count ?? "-").padStart(3)} {actionMix}
      </Text>
      <Text>
        {" ".repeat(6)} exit_alpha{" "}
        {summary?.metric_availability.exit_after_hold_alpha ?? "requires_stage2_scored_positions"}{" "}
        reduce_cost{" "}
        {summary?.metric_availability.reduce_opportunity_cost ?? "requires_stage2_scored_positions"}{" "}
        stop_loss_drawdown{" "}
        {summary?.metric_availability.stop_loss_avoided_drawdown ??
          "requires_stage2_scored_positions"}
      </Text>
    </Box>
  );
}

function formatNumberOrDash(value: number | undefined): string {
  return value === undefined ? "-" : value.toFixed(3);
}

function PaperExecutionRow({
  row,
  latestTrade,
}: {
  row: ActionDisplayRow;
  latestTrade: PaperTrade | undefined;
}) {
  const submitted = latestTrade ? `${latestTrade.side} ${latestTrade.quantity}` : "-";
  const filled = latestTrade
    ? `${latestTrade.side} ${latestTrade.quantity}@${latestTrade.price.toFixed(2)}`
    : "-";
  return (
    <Box flexDirection="column">
      <Text>
        {row.ticker.padEnd(11)} current {row.currentWeightPct.toFixed(1).padStart(5)}% target{" "}
        {row.targetWeightPct.toFixed(1).padStart(5)}% required_delta{" "}
        {row.deltaWeightPct.toFixed(1).padStart(6)}%
      </Text>
      <Text>
        {" ".repeat(11)} submitted {submitted} filled {filled} residual{" "}
        {row.deltaWeightPct.toFixed(1)}%
      </Text>
    </Box>
  );
}

function latestTradeMap(trades: ReadonlyArray<PaperTrade>): Map<string, PaperTrade> {
  const out = new Map<string, PaperTrade>();
  for (const trade of trades) {
    if (!out.has(trade.ticker)) out.set(trade.ticker, trade);
  }
  return out;
}

function currentPaperWeights(
  account: PaperAccount | null,
  positions: ReadonlyArray<PaperPosition>,
): Map<string, number> {
  const total =
    account?.total_assets ?? positions.reduce((sum, item) => sum + item.market_value, 0);
  return new Map(
    positions.map((position) => [
      position.ticker,
      total > 0 ? (position.market_value / total) * 100 : 0,
    ]),
  );
}

function CohortsTab({ cohorts }: { cohorts: CohortInfo[] }) {
  if (cohorts.length === 0) return <Text dimColor>no cohorts</Text>;
  return (
    <Box flexDirection="column">
      <Text color="cyan">{`cohort               runs  branch  last_run`}</Text>
      {cohorts.map((c) => (
        <Text key={c.name}>
          {c.name.padEnd(20)} {String(c.n_runs).padStart(4)} {c.has_branch ? "yes" : "no "}{" "}
          {c.last_run_date ?? "—"}
        </Text>
      ))}
    </Box>
  );
}

function fmt(v: number | null): string {
  return v == null ? "n/a" : v.toFixed(4);
}

function formatPercentOrDash(value: number | undefined): string {
  return value === undefined ? "-" : `${(value * 100).toFixed(1)}%`;
}

interface ActionDisplayRow {
  ticker: string;
  action: string;
  positionDecision: string;
  currentWeightPct: number;
  targetWeightPct: number;
  deltaWeightPct: number;
  thesisStatus: string;
  riskFlags: string[];
  influenceIds: string[];
  firedCaps: string[];
  notes: string;
}

function actionDisplay(
  action: CioAction,
  currentWeights: ReadonlyMap<string, number>,
): ActionDisplayRow {
  const targetWeightPct = action.target_weight_pct ?? 0;
  const currentWeightPct = action.current_weight_pct ?? currentWeights.get(action.ticker) ?? 0;
  const deltaWeightPct = action.delta_weight_pct ?? targetWeightPct - currentWeightPct;
  return {
    ticker: action.ticker,
    action: action.action,
    positionDecision:
      action.position_decision ?? inferPositionDecision(action.action, deltaWeightPct),
    currentWeightPct,
    targetWeightPct,
    deltaWeightPct,
    thesisStatus: action.thesis_status ?? "-",
    riskFlags: parseRiskFlags(action.risk_flags_json),
    influenceIds: parseStringArrayJson(action.declared_knob_influence_ids_json),
    firedCaps: parseAuditStringArray(action.verified_knob_audit_json, "fired_cap_ids"),
    notes: firstNonEmpty(
      action.dissent_notes,
      action.override_reason,
      action.position_decision_reason,
      action.declared_influence_rationale,
      action.rationale_snapshot,
    ),
  };
}

function inferPositionDecision(action: string, deltaWeightPct: number): string {
  if (action === "SELL") return "EXIT";
  if (action === "REDUCE") return "REDUCE";
  if (action === "HOLD") return "HOLD";
  return deltaWeightPct > 0 ? "ADD" : "HOLD";
}

function parseRiskFlags(value: string | null | undefined): string[] {
  return parseStringArrayJson(value);
}

function parseStringArrayJson(value: string | null | undefined): string[] {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed.map((item) => String(item)) : [];
  } catch {
    return [];
  }
}

function formatFlagsAndNotes(row: ActionDisplayRow): string {
  const flags = row.riskFlags.length > 0 ? row.riskFlags.join("|") : "-";
  const caps = row.firedCaps.length > 0 ? row.firedCaps.join("|") : "-";
  const influence = row.influenceIds.length > 0 ? row.influenceIds.join("|") : "-";
  return `${flags} caps=${caps} influence=${influence} ${row.notes}`;
}

function firstNonEmpty(...values: Array<string | null | undefined>): string {
  return values.find((value) => value != null && value.trim().length > 0) ?? "";
}

function parseAuditStringArray(value: string | null | undefined, key: string): string[] {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value) as Record<string, unknown>;
    const raw = parsed[key];
    return Array.isArray(raw) ? raw.map((item) => String(item)) : [];
  } catch {
    return [];
  }
}

function formatDecisionAgentAudits(actions: ReadonlyArray<CioAction>): string | null {
  const raw = actions.find(
    (action) => action.decision_agent_audits_json,
  )?.decision_agent_audits_json;
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Record<string, Record<string, unknown>>;
    const parts = ["cro", "autonomous_execution", "cio"].flatMap((agent) => {
      const audit = parsed[agent];
      if (!audit) return [];
      const caps = stringArrayField(audit, "fired_cap_ids").join("|") || "-";
      const influence = stringArrayField(audit, "declared_knob_influence_ids").join("|") || "-";
      const unsupported =
        stringArrayField(audit, "unsupported_knob_influence_ids").join("|") || "-";
      return [`${agent} caps=${caps} influence=${influence} unsupported=${unsupported}`];
    });
    return parts.length > 0 ? `agent detail ${parts.join(" ; ")}` : null;
  } catch {
    return null;
  }
}

function stringArrayField(obj: Record<string, unknown>, key: string): string[] {
  const raw = obj[key];
  return Array.isArray(raw) ? raw.map((item) => String(item)) : [];
}

function isPositionStale(position: PaperPosition, runDate: string | null): boolean {
  if (!runDate || !position.updated_at) return false;
  const updatedDate = position.updated_at.slice(0, 10);
  return updatedDate.length === 10 && updatedDate < runDate;
}

function MirofishTab({
  context,
  runs,
}: {
  context: MirofishContext | null;
  runs: MirofishHistoryEntry[];
}) {
  return (
    <Box flexDirection="column">
      <Text color="cyan">latest scenario context</Text>
      {!context ? (
        <Text dimColor>no scenario context — run `mirofish generate` + save_context</Text>
      ) : (
        <Box flexDirection="column">
          <Text>
            {`${context.date ?? "—"}  engine=${context.engine}  regime=${context.regime ?? "—"}` +
              `  CSI300 ${((context.csi300_return ?? 0) * 100).toFixed(1)}%`}
          </Text>
          <Text dimColor>
            {`scenarios=${context.scenario_count ?? context.n_scenarios} horizon=${context.horizon_days ?? "—"}d ` +
              `as_of=${context.as_of_date ?? context.date ?? "—"} hash=${context.context_hash ?? "—"} ` +
              `version=${context.generator_version ?? "—"} simulation_only=current_data_gate_required`}
          </Text>
          <Text>
            {`最高信念: ${context.hct_direction ?? "—"} ${context.hct_ticker}` +
              `（${((context.hct_csi300_return ?? 0) * 100).toFixed(1)}%）`}
          </Text>
          {context.tail_summary ? (
            <Text color="red">{`尾部风险: ${context.tail_summary}`}</Text>
          ) : null}
          {context.position_stress && context.position_stress.length > 0 ? (
            <Box flexDirection="column">
              <Text color="cyan">per-position stress</Text>
              {context.position_stress.slice(0, 8).map((stress) => (
                <Text key={stress.ticker}>
                  {stress.ticker.padEnd(11)} tail{" "}
                  {formatPercentOrDash(stress.tail_loss).padStart(7)} agree{" "}
                  {formatPercentOrDash(stress.scenario_agreement).padStart(7)} action{" "}
                  {stress.suggested_action ?? "-"}
                </Text>
              ))}
            </Box>
          ) : null}
        </Box>
      )}
      <Box marginTop={1} flexDirection="column">
        <Text color="cyan">recent forward-training runs</Text>
        {runs.length === 0 ? (
          <Text dimColor>no runs — run `mirofish train`</Text>
        ) : (
          runs.slice(0, 8).map((r) => (
            <Text key={r.id}>
              {(r.date ?? "—").padEnd(12)} {r.agent.padEnd(16)} {(r.scenario_type ?? "").padEnd(10)}{" "}
              {r.avg_score != null ? r.avg_score.toFixed(3) : "n/a"}
            </Text>
          ))
        )}
      </Box>
    </Box>
  );
}

// ---------------------------------------------------------------------------
// Settings tab (key 7): curated, editable, persisted config (config.save)
// ---------------------------------------------------------------------------

type FieldKind = "string" | "number" | "bool" | "enum";

interface FieldSpec {
  /** Dotted path into the config object, e.g. "autoresearch.git.push". */
  path: string;
  label: string;
  kind: FieldKind;
  options?: string[]; // for enum
}

/** Curated fields — the commonly-tuned knobs, not arbitrary nested maps. */
const FIELDS: FieldSpec[] = [
  {
    path: "llm_provider",
    label: "LLM provider",
    kind: "enum",
    options: ["anthropic", "openai", "deepseek", "lemonade"],
  },
  { path: "deep_think_llm", label: "Deep-think model", kind: "string" },
  { path: "quick_think_llm", label: "Quick-think model", kind: "string" },
  {
    path: "output_language",
    label: "Output language",
    kind: "enum",
    options: ["Chinese", "English", "Bilingual"],
  },
  { path: "active_cohort", label: "Active cohort", kind: "string" },
  { path: "autoresearch.keep_threshold_delta_sharpe", label: "AR keep ΔSharpe", kind: "number" },
  { path: "autoresearch.agent_mutation_cooldown_hours", label: "AR cooldown (h)", kind: "number" },
  { path: "autoresearch.keep_revert_lockout_days", label: "AR lockout (d)", kind: "number" },
  {
    path: "autoresearch.monthly_modification_cap_per_cohort",
    label: "AR monthly cap",
    kind: "number",
  },
  {
    path: "autoresearch.evaluation_horizon_trading_days",
    label: "AR eval horizon (d)",
    kind: "number",
  },
  { path: "autoresearch.git.push", label: "AR git push", kind: "bool" },
  { path: "autoresearch.git.remote", label: "AR git remote", kind: "string" },
  {
    path: "mirofish.engine",
    label: "MiroFish engine",
    kind: "enum",
    options: ["montecarlo", "swarm"],
  },
  {
    path: "mirofish.scorer",
    label: "MiroFish scorer",
    kind: "enum",
    options: ["terminal", "path_aware"],
  },
  { path: "mirofish.inject_context", label: "MiroFish inject ctx", kind: "bool" },
];

function getPath(obj: Record<string, unknown>, path: string): unknown {
  return path.split(".").reduce<unknown>((acc, k) => {
    return acc && typeof acc === "object" ? (acc as Record<string, unknown>)[k] : undefined;
  }, obj);
}

function setPath(obj: Record<string, unknown>, path: string, value: unknown): void {
  const keys = path.split(".");
  let node = obj;
  for (const k of keys.slice(0, -1)) {
    if (typeof node[k] !== "object" || node[k] === null) node[k] = {};
    node = node[k] as Record<string, unknown>;
  }
  node[keys[keys.length - 1] as string] = value;
}

function display(value: unknown, kind: FieldKind): string {
  if (value === undefined || value === null) return kind === "bool" ? "false" : "—";
  if (kind === "bool") return value ? "true" : "false";
  return String(value);
}

function SettingsTab({
  api,
  onEditingChange,
}: {
  api: Pick<BridgeApi, "configGet" | "configDefault" | "configSave">;
  onEditingChange: (editing: boolean) => void;
}) {
  const [cfg, setCfg] = useState<MosaicConfig | null>(null);
  const [sel, setSel] = useState(0);
  const [editing, setEditing] = useState(false);
  const [buffer, setBuffer] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    api
      .configGet()
      .catch(() => api.configDefault())
      .then((c) => {
        if (mounted.current) setCfg(c);
      })
      .catch((e) => {
        if (mounted.current) setStatus(`load error: ${(e as Error).message}`);
      });
    return () => {
      mounted.current = false;
    };
  }, [api]);

  // Keep the parent informed so it can gate its own input handler.
  useEffect(() => onEditingChange(editing), [editing, onEditingChange]);

  const save = useCallback(async () => {
    if (!cfg) return;
    try {
      const applied = await api.configSave(cfg);
      if (mounted.current) {
        setCfg(applied);
        setStatus("saved → ~/.mosaic/config.json");
      }
    } catch (e) {
      if (mounted.current) setStatus(`save error: ${(e as Error).message}`);
    }
  }, [api, cfg]);

  useInput((input, key) => {
    if (!cfg) return;
    const field = FIELDS[sel] as FieldSpec;
    if (editing) {
      // Edit mode (string/number): type chars, enter commits, esc cancels.
      if (key.escape) {
        setEditing(false);
        setBuffer("");
      } else if (key.return) {
        const next = structuredClone(cfg) as Record<string, unknown>;
        setPath(next, field.path, field.kind === "number" ? Number(buffer) : buffer);
        setCfg(next as MosaicConfig);
        setEditing(false);
        setBuffer("");
        setStatus("edited (unsaved) — press s to persist");
      } else if (key.backspace || key.delete) {
        setBuffer((b) => b.slice(0, -1));
      } else if (input && !key.ctrl && !key.meta) {
        setBuffer((b) => b + input);
      }
      return;
    }
    // Browse mode.
    if (key.upArrow) setSel((s) => (s - 1 + FIELDS.length) % FIELDS.length);
    else if (key.downArrow) setSel((s) => (s + 1) % FIELDS.length);
    else if (input === "s") void save();
    else if (input === " " && (field.kind === "bool" || field.kind === "enum")) {
      const next = structuredClone(cfg) as Record<string, unknown>;
      if (field.kind === "bool") {
        setPath(next, field.path, !getPath(next, field.path));
      } else {
        const opts = field.options ?? [];
        const cur = String(getPath(next, field.path) ?? opts[0]);
        const idx = opts.indexOf(cur);
        setPath(next, field.path, opts[(idx + 1) % opts.length]);
      }
      setCfg(next as MosaicConfig);
      setStatus("edited (unsaved) — press s to persist");
    } else if (key.return && (field.kind === "string" || field.kind === "number")) {
      setBuffer(display(getPath(cfg as Record<string, unknown>, field.path), field.kind));
      setEditing(true);
    }
  });

  if (status?.startsWith("load error")) return <Text color="red">{status}</Text>;
  if (!cfg) return <Text color="yellow">loading config…</Text>;

  return (
    <Box flexDirection="column">
      <Text color="cyan">settings (persisted to ~/.mosaic/config.json)</Text>
      {FIELDS.map((f, i) => {
        const active = i === sel;
        const val = display(getPath(cfg as Record<string, unknown>, f.path), f.kind);
        const shown = active && editing ? `${buffer}▌` : val;
        return (
          <Text key={f.path} color={active ? "cyan" : "gray"} bold={active}>
            {active ? "›" : " "} {f.label.padEnd(22)} {shown}
          </Text>
        );
      })}
      <Box marginTop={1}>
        <Text dimColor>
          {editing
            ? "[type] edit · [enter] commit · [esc] cancel"
            : "[↑↓] select · [enter] edit · [space] toggle/cycle · [s] save"}
          {status ? `  ·  ${status}` : ""}
        </Text>
      </Box>
    </Box>
  );
}
