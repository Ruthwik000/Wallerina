"use client";

import { useEffect, useState } from "react";
import Button from "@/components/Button";
import GoalDialog from "@/components/GoalDialog";
import PageHeader from "@/components/PageHeader";
import PageState from "@/components/PageState";
import Panel from "@/components/Panel";
import { ErrorState, Loading, Notice } from "@/components/States";
import Table from "@/components/Table";
import { useWallet } from "@/components/WalletProvider";
import { fetchRecommendation, fetchRecommendationHistory } from "@/lib/api";
import { quantity, ratio, timeLabel, usd } from "@/lib/format";
import styles from "../page.module.css";

const GOAL_TYPES = {
  aggressive_growth: "Aggressive growth",
  growth: "Growth",
  balanced: "Balanced",
  save_over_time: "Save over time",
  capital_preservation: "Capital preservation",
};

const AGENTS = {
  wallet: "Wallet agent",
  market: "Market agent",
  stablecoin: "Stablecoin agent",
};

const SCENARIO_COLUMNS = [
  { key: "name", header: "Allocation" },
  { key: "stablecoin_ratio", header: "Stablecoin", align: "right" },
  { key: "expected_value", header: "Expected", align: "right" },
  { key: "p5", header: "5th percentile", align: "right" },
  { key: "expected_drawdown", header: "Expected drawdown", align: "right" },
  { key: "probability_of_loss", header: "Loss probability", align: "right" },
];

const TRADE_COLUMNS = [
  { key: "action", header: "Action" },
  { key: "symbol", header: "Asset" },
  { key: "value_usd", header: "Value", align: "right" },
  { key: "quantity", header: "Quantity", align: "right" },
  { key: "reason", header: "Why" },
];

const POSITION_COLUMNS = [
  { key: "action", header: "After rebalance" },
  { key: "symbol", header: "Asset" },
  { key: "classification", header: "Type" },
  { key: "value_before_usd", header: "Before", align: "right" },
  { key: "value_after_usd", header: "After", align: "right" },
  { key: "ratio_after", header: "Share after", align: "right" },
];

// Measures compared as held and after the rebalance, on identical market draws.
const OUTLOOK_METRICS = [
  { key: "expected_value", label: "Expected value", kind: "usd" },
  { key: "median_value", label: "Median value", kind: "usd" },
  { key: "p5", label: "5th percentile value", kind: "usd" },
  { key: "probability_of_loss", label: "Probability of loss", kind: "ratio" },
  { key: "expected_drawdown", label: "Expected drawdown", kind: "ratio" },
  { key: "max_drawdown_p95", label: "Drawdown in the worst 5% of paths", kind: "ratio" },
];

const OUTLOOK_COLUMNS = [
  { key: "label", header: "Measure" },
  { key: "current", header: "As held", align: "right" },
  { key: "target", header: "After rebalance", align: "right" },
  { key: "change", header: "Change", align: "right" },
];

function formatMeasure(value, kind) {
  return kind === "usd" ? usd(value, { decimals: 0 }) : ratio(value);
}

function formatChange(current, target, kind) {
  if (current == null || target == null) return "—";
  const difference = target - current;
  if (kind === "usd") {
    return `${difference < 0 ? "−" : "+"}${usd(Math.abs(difference), { decimals: 0 })}`;
  }
  return ratio(difference, { sign: true });
}

const HISTORY_COLUMNS = [
  { key: "generated_at", header: "When" },
  { key: "goal", header: "Goal" },
  { key: "target_ratio", header: "Target", align: "right" },
  { key: "current_ratio", header: "Held", align: "right" },
  { key: "rebalance", header: "Rebalance" },
  { key: "confidence", header: "Confidence", align: "right" },
];

const humanise = (value) => (value ? String(value).replaceAll("_", " ") : "");

function Stat({ label, value, note, strong = false }) {
  return (
    <div>
      <p className={styles.statLabel}>{label}</p>
      <p className={strong ? styles.statValueStrong : styles.statValue}>{value}</p>
      {note && <p className={styles.statNote}>{note}</p>}
    </div>
  );
}

export default function RecommendationsPage() {
  const [goalOpen, setGoalOpen] = useState(false);
  const [runId, setRunId] = useState(0);
  const rerun = () => setRunId((current) => current + 1);

  const header = (
    <PageHeader
      eyebrow="Analysis"
      title="Recommendations"
      description="Your goal sets the rules. The wallet, market and stablecoin agents read the evidence, the allocation engine sets the target, and the grounding agent checks every figure in the explanation against the engine."
      actions={
        <div className={styles.headerActions}>
          <Button variant="ghost" onClick={() => setGoalOpen(true)}>
            Change goal
          </Button>
          <Button variant="ghost" onClick={rerun}>
            Re-run agents
          </Button>
          <Button href="/chat" variant="ghost">
            Ask about these numbers
          </Button>
        </div>
      }
    />
  );

  return (
    <>
      <PageState header={header} loadingLabel="Reading the wallet">
        {() => (
          <RecommendationView runId={runId} onChangeGoal={() => setGoalOpen(true)} onRerun={rerun} />
        )}
      </PageState>
      <GoalDialog open={goalOpen} onClose={() => setGoalOpen(false)} />
    </>
  );
}

function RecommendationView({ runId, onChangeGoal, onRerun }) {
  const { address, goal, goalStatus, scenarios, simulation } = useWallet();
  const [result, setResult] = useState({ status: "idle", data: null, error: null });
  const [history, setHistory] = useState([]);

  useEffect(() => {
    if (!address || !goal) return undefined;

    const controller = new AbortController();
    setResult((current) => ({ ...current, status: "loading", error: null }));

    fetchRecommendation(address, { goal, signal: controller.signal })
      .then((data) => {
        setResult({ status: "ready", data, error: null });
        return fetchRecommendationHistory(address, { signal: controller.signal })
          .then((rows) => setHistory(Array.isArray(rows) ? rows : []))
          .catch(() => {
            // History is supplementary; the recommendation stands without it.
          });
      })
      .catch((error) => {
        if (error.name === "AbortError") return;
        setResult((current) => ({ status: "error", data: current.data, error }));
      });

    return () => controller.abort();
  }, [address, goal, runId]);

  if (!goal) {
    if (goalStatus === "loading") return <Loading label="Loading your goal" />;
    return (
      <Panel title="Choose a goal first" meta="The allocation depends on what this wallet is for">
        <div className={styles.prose}>
          <p>
            Every agent works within rules set by your goal: how much of the wallet
            may sit in volatile assets, the largest loss you would accept and the
            horizon that matters. Pick a preset or describe it in your own words.
          </p>
        </div>
        <div className={styles.panelActions}>
          <Button onClick={onChangeGoal}>Choose a goal</Button>
        </div>
      </Panel>
    );
  }

  if (result.status === "error" && !result.data) {
    return <ErrorState error={result.error} title="The agents could not finish" onRetry={onRerun} />;
  }

  if (!result.data) {
    return (
      <Loading
        label="Running the agents"
        detail="Goal agent, then the wallet, market and stablecoin agents, the allocation engine, the explanation and the grounding check. A goal written in your own words is read by the model, so this can take up to a minute."
      />
    );
  }

  const { data } = result;
  const { decision, intent, rules, judgement } = data;
  const drivers = [...decision.drivers].sort(
    (a, b) => Math.abs(b.contribution) - Math.abs(a.contribution)
  );
  const grounding = judgement?.grounding;
  const scenarioRows = scenarios ?? [];
  const tradeRows = data.trades.map((trade, index) => ({ ...trade, key: `${trade.action}-${trade.symbol}-${index}` }));
  const positionRows = data.holdings_after ?? [];
  const outlook = data.outlook;
  const outlookRows = outlook
    ? OUTLOOK_METRICS.map((metric) => ({
        ...metric,
        current: outlook.current[metric.key],
        target: outlook.target?.[metric.key],
      }))
    : [];
  const warnings = data.warnings ?? [];

  return (
    <div className={styles.stackWide}>
      {result.status === "loading" && <Notice>Re-running the agents for “{goal}”…</Notice>}
      {result.status === "error" && (
        <Notice>
          The latest run failed ({result.error?.detail || result.error?.message}); showing the previous result.
        </Notice>
      )}
      {warnings.length > 0 && (
        <Notice>Part of this run was degraded: {warnings.join("; ")}.</Notice>
      )}

      <div className={`${styles.statRow} ${styles.statRow4}`}>
        <Stat
          label="Target stablecoin"
          value={ratio(decision.target_stablecoin_ratio)}
          note={`Acceptable ${ratio(decision.acceptable_range[0])} – ${ratio(decision.acceptable_range[1])}`}
          strong
        />
        <Stat
          label="Held today"
          value={ratio(decision.current_stablecoin_ratio)}
          note={`Drift ${ratio(decision.drift, { sign: true })}`}
        />
        <Stat
          label="Rebalance"
          value={decision.rebalance_required ? "Recommended" : "Not needed"}
          note={`Threshold ${ratio(rules.rebalance_threshold)}`}
        />
        <Stat
          label="Engine confidence"
          value={ratio(decision.confidence, { decimals: 0 })}
          note={decision.binding_constraint ? `Capped by ${humanise(decision.binding_constraint)}` : "No rule was binding"}
        />
      </div>

      <div className={`${styles.grid} ${styles.split}`}>
        <Panel
          title="Why this allocation"
          meta={
            judgement
              ? judgement.used_model
                ? "Written by the model, verified by the grounding agent"
                : "Deterministic write-up from the engine's drivers"
              : "No explanation requested"
          }
          action={
            grounding && (
              <span className={`${styles.badge} ${grounding.replaced_model_output ? "" : styles.badgeGood}`}>
                {grounding.replaced_model_output
                  ? `Model text rejected · ${grounding.rejected.length} unverified`
                  : `Grounded · ${grounding.figures_checked} figures verified`}
              </span>
            )
          }
        >
          {judgement ? (
            <div className={styles.prose}>
              <p className={styles.lead}>{judgement.summary}</p>
              {judgement.reasoning.map((paragraph, index) => (
                <p key={index}>{paragraph}</p>
              ))}
              {grounding?.replaced_model_output && (
                <Notice>
                  The model cited figures the engine never produced ({grounding.rejected.join(", ")}),
                  so its text was replaced with this write-up.
                </Notice>
              )}
              {judgement.caveats.length > 0 && (
                <>
                  <p className={styles.subhead}>Caveats</p>
                  <ul className={styles.caveats}>
                    {judgement.caveats.map((caveat, index) => (
                      <li key={index}>{caveat}</li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          ) : (
            <p className={styles.helper}>No explanation was generated.</p>
          )}
        </Panel>

        <Panel
          title="Your goal"
          meta={intent.source === "preset" ? "Preset — resolved without a model call" : "Read by the goal agent"}
          action={
            <Button variant="ghost" size="sm" onClick={onChangeGoal}>
              Change
            </Button>
          }
        >
          <p className={styles.goalText}>“{goal}”</p>
          {intent.interpretation && <p className={styles.factorNote}>{intent.interpretation}</p>}
          <dl className={styles.defs}>
            <div className={`${styles.def} ${styles.defStrong}`}>
              <dt>Read as</dt>
              <dd>{GOAL_TYPES[intent.goal_type] ?? humanise(intent.goal_type)}</dd>
            </div>
            <div className={styles.def}>
              <dt>Risk tolerance</dt>
              <dd>{humanise(intent.risk_tolerance)}</dd>
            </div>
            <div className={styles.def}>
              <dt>Largest acceptable loss</dt>
              <dd>{ratio(intent.maximum_drawdown, { decimals: 0 })}</dd>
            </div>
            <div className={styles.def}>
              <dt>Horizon</dt>
              <dd>{rules.time_horizon_days} days</dd>
            </div>
            <div className={styles.def}>
              <dt>Stablecoin bounds</dt>
              <dd>
                {ratio(rules.minimum_stablecoin_ratio, { decimals: 0 })} –{" "}
                {ratio(rules.maximum_stablecoin_ratio, { decimals: 0 })}
              </dd>
            </div>
          </dl>
        </Panel>
      </div>

      <Panel
        title="What moved the target"
        meta={
          decision.drawdown_at_target != null
            ? `Largest first · simulated drawdown at target ${ratio(decision.drawdown_at_target)}`
            : "Largest first · signed shift in the stablecoin target"
        }
        flush
      >
        <ul className={styles.indicators}>
          {drivers.map((driver) => (
            <li key={driver.name} className={styles.driverRow}>
              <div>
                <p className={styles.indicatorName}>{driver.name}</p>
                <p className={styles.factorNote}>{driver.detail}</p>
              </div>
              <span className={styles.indicatorValue}>{ratio(driver.contribution, { sign: true })}</span>
            </li>
          ))}
        </ul>
      </Panel>

      <div className={`${styles.grid} ${styles.cols3}`}>
        {data.reports.map((report) => (
          <Panel key={report.agent} title={AGENTS[report.agent] ?? humanise(report.agent)} meta={report.headline} flush>
            <ul className={styles.findings}>
              {report.findings.map((finding, index) => (
                <li key={`${finding.label}-${index}`} className={styles.finding}>
                  <div className={styles.findingHead}>
                    <span className={styles.findingLabel}>{finding.label}</span>
                    <span className={`${styles.severity} ${styles[`severity_${finding.severity}`] ?? ""}`}>
                      {finding.severity}
                    </span>
                  </div>
                  <p className={styles.findingDetail}>{finding.detail}</p>
                </li>
              ))}
            </ul>
          </Panel>
        ))}
      </div>

      <Panel title="Proposed rebalance" meta="Recommendation only — nothing is ever executed" flush>
        {tradeRows.length === 0 ? (
          <p className={styles.helper}>
            {decision.rebalance_required
              ? "A rebalance is recommended, but there are no positions to move toward the target."
              : "The wallet is within its acceptable range, so no trades are proposed."}
          </p>
        ) : (
          <Table
            columns={TRADE_COLUMNS}
            rows={tradeRows}
            rowKey={(row) => row.key}
            renderCell={(row, column) => {
              switch (column.key) {
                case "action":
                  return <span className={styles.txType}>{row.action}</span>;
                case "symbol":
                  return <span className={styles.assetSymbol}>{row.symbol}</span>;
                case "value_usd":
                  return usd(row.value_usd, { decimals: 0 });
                case "quantity":
                  return quantity(row.quantity, row.symbol);
                default:
                  return row.reason;
              }
            }}
          />
        )}
      </Panel>

      <Panel
        title="Positions after rebalance"
        meta={
          tradeRows.length
            ? "What you would keep, reduce and add · positions under 0.5% of the wallet are omitted"
            : "No trades proposed, so every position is held"
        }
        flush
      >
        {positionRows.length === 0 ? (
          <p className={styles.helper}>No positions to show.</p>
        ) : (
          <Table
            columns={POSITION_COLUMNS}
            rows={positionRows}
            rowKey={(row) => row.symbol}
            renderCell={(row, column) => {
              switch (column.key) {
                case "action":
                  return <span className={styles.txType}>{row.action}</span>;
                case "symbol":
                  return <span className={styles.assetSymbol}>{row.symbol}</span>;
                case "classification":
                  return humanise(row.classification);
                case "value_before_usd":
                case "value_after_usd":
                  return usd(row[column.key], { decimals: 0 });
                default:
                  return ratio(row.ratio_after);
              }
            }}
          />
        )}
      </Panel>

      {outlook && (
        <Panel
          title="After rebalance"
          meta={`Monte Carlo · ${outlook.horizon_days}-day horizon · ${outlook.simulations.toLocaleString("en-US")} paths · identical market draws for both columns`}
          flush
        >
          {outlook.note && <p className={styles.helper}>{outlook.note}</p>}
          <Table
            columns={OUTLOOK_COLUMNS}
            rows={outlookRows}
            rowKey={(row) => row.key}
            renderCell={(row, column) => {
              switch (column.key) {
                case "current":
                case "target":
                  return formatMeasure(row[column.key], row.kind);
                case "change":
                  return formatChange(row.current, row.target, row.kind);
                default:
                  return row.label;
              }
            }}
          />
        </Panel>
      )}

      <Panel
        title="Allocation evidence"
        meta={`${simulation.horizon_days}-day horizon · identical market draws across rows`}
        flush
      >
        {scenarioRows.length === 0 ? (
          <p className={styles.helper}>
            No scenarios available. This wallet holds no recognised stablecoin, so
            there is nothing to rotate capital into.
          </p>
        ) : (
          <Table
            columns={SCENARIO_COLUMNS}
            rows={scenarioRows}
            rowKey={(row) => row.name}
            renderCell={(row, column) => {
              switch (column.key) {
                case "stablecoin_ratio":
                  return ratio(row.stablecoin_ratio, { decimals: 1 });
                case "expected_value":
                case "p5":
                  return usd(row[column.key], { decimals: 0 });
                case "expected_drawdown":
                case "probability_of_loss":
                  return ratio(row[column.key]);
                default:
                  return row.name;
              }
            }}
          />
        )}
      </Panel>

      <Panel
        title="History"
        meta={history.length ? `${history.length} most recent runs for this wallet` : "Every run is logged with its inputs"}
        flush
      >
        {history.length === 0 ? (
          <p className={styles.helper}>
            No saved runs yet. Recommendations are stored once the database is connected.
          </p>
        ) : (
          <Table
            columns={HISTORY_COLUMNS}
            rows={history}
            rowKey={(row) => row.generated_at}
            renderCell={(row, column) => {
              switch (column.key) {
                case "generated_at":
                  return timeLabel(row.generated_at);
                case "goal":
                  return GOAL_TYPES[row.goal] ?? humanise(row.goal);
                case "target_ratio":
                case "current_ratio":
                  return ratio(row[column.key]);
                case "rebalance":
                  return row.rebalance ? "Yes" : "No";
                default:
                  return ratio(row.confidence, { decimals: 0 });
              }
            }}
          />
        )}
      </Panel>
    </div>
  );
}
