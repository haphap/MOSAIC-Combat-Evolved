/**
 * Phase 9B: read-only Ink dashboard. Aggregates three existing read RPCs into
 * one live screen — no new bridge methods. Tabs: 1 Skill / 2 Paper / 3 Cohorts;
 * keys r=refresh, q=quit. The BridgeApi is injected so the component is testable
 * with a fake.
 */

import { Box, Text, useApp, useInput } from "ink";
import { useCallback, useEffect, useState } from "react";
import type {
  BridgeApi,
  CohortInfo,
  PaperAccount,
  PaperPosition,
  SkillRow,
} from "../bridge/types.js";

type Tab = "skill" | "paper" | "cohorts";
const TABS: Tab[] = ["skill", "paper", "cohorts"];

interface Props {
  api: Pick<
    BridgeApi,
    "scorecardListSkill" | "paperGetAccount" | "paperGetPositions" | "prismListCohorts"
  >;
  cohort: string;
  user?: string;
}

interface Data {
  skill: SkillRow[];
  account: PaperAccount | null;
  positions: PaperPosition[];
  cohorts: CohortInfo[];
}

export function Dashboard({ api, cohort, user }: Props) {
  const { exit } = useApp();
  const [tab, setTab] = useState<Tab>("skill");
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [skill, account, positions, cohorts] = await Promise.all([
        api.scorecardListSkill(cohort).then((r) => r.rows),
        api.paperGetAccount(user ? { user_id: user } : {}).catch(() => null),
        api.paperGetPositions(user ? { user_id: user } : {}).catch(() => []),
        api.prismListCohorts().then((r) => r.cohorts),
      ]);
      setData({ skill, account, positions, cohorts });
    } catch (err) {
      setError((err as Error).message);
    }
  }, [api, cohort, user]);

  useEffect(() => {
    void load();
  }, [load]);

  useInput((input) => {
    if (input === "q") exit();
    else if (input === "r") void load();
    else if (input === "1") setTab("skill");
    else if (input === "2") setTab("paper");
    else if (input === "3") setTab("cohorts");
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
        ) : !data ? (
          <Text color="yellow">loading…</Text>
        ) : tab === "skill" ? (
          <SkillTab rows={data.skill} cohort={cohort} />
        ) : tab === "paper" ? (
          <PaperTab account={data.account} positions={data.positions} />
        ) : (
          <CohortsTab cohorts={data.cohorts} />
        )}
      </Box>
      <Box marginTop={1}>
        <Text dimColor>[1/2/3] switch · [r] refresh · [q] quit</Text>
      </Box>
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
