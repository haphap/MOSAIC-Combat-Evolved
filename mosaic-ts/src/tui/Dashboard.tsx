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
  BridgeApi,
  CioActions,
  CohortInfo,
  MirofishContext,
  MirofishHistoryEntry,
  MosaicConfig,
  PaperAccount,
  PaperPosition,
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
      const [today, winrate, skill, account, positions, cohorts] = await Promise.all([
        api.scorecardLatestCioActions(cohort),
        api.scorecardWinRate(cohort).then((r) => r.rows),
        api.scorecardListSkill(cohort).then((r) => r.rows),
        api.paperGetAccount(user ? { user_id: user } : {}).catch(() => null),
        api.paperGetPositions(user ? { user_id: user } : {}).catch(() => []),
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
      if (mounted.current)
        setData({
          today,
          winrate,
          skill,
          account,
          positions,
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
          <TodayTab today={data.today} />
        ) : tab === "winrate" ? (
          <WinRateTab rows={data.winrate} cohort={cohort} />
        ) : tab === "skill" ? (
          <SkillTab rows={data.skill} cohort={cohort} />
        ) : tab === "paper" ? (
          <PaperTab account={data.account} positions={data.positions} />
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

function TodayTab({ today }: { today: CioActions }) {
  if (!today.date || today.actions.length === 0)
    return <Text dimColor>no CIO recommendations yet — run a daily cycle first</Text>;
  return (
    <Box flexDirection="column">
      <Text color="cyan">{`today's CIO plan (${today.date})   ticker      action  weight%  why`}</Text>
      {today.actions.map((a) => (
        <Text key={a.ticker}>
          {a.ticker.padEnd(11)} {a.action.padEnd(6)}{" "}
          {String((a.target_weight_pct ?? 0).toFixed(1)).padStart(6)} {a.rationale_snapshot ?? ""}
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
}: {
  account: PaperAccount | null;
  positions: PaperPosition[];
}) {
  if (!account) return <Text dimColor>no paper account (login first)</Text>;
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
            {p.ticker.padEnd(11)} qty {String(p.quantity).padStart(6)} pnl% {p.pnl_pct.toFixed(2)}
          </Text>
        ))
      )}
    </Box>
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
          <Text>
            {`最高信念: ${context.hct_direction ?? "—"} ${context.hct_ticker}` +
              `（${((context.hct_csi300_return ?? 0) * 100).toFixed(1)}%）`}
          </Text>
          {context.tail_summary ? (
            <Text color="red">{`尾部风险: ${context.tail_summary}`}</Text>
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
