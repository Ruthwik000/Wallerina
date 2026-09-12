"use client";

import { useEffect, useRef, useState } from "react";
import Meter from "@/components/Meter";
import Panel from "@/components/Panel";
import Stat from "@/components/Stat";
import Table from "@/components/Table";
import { Empty, Loading } from "@/components/States";
import LineChart from "@/components/charts/LineChart";
import { fetchPriceHistory } from "@/lib/api";
import { quantity, ratio, usd } from "@/lib/format";
import styles from "../page.module.css";

const COLUMNS = [
  { key: "symbol", header: "Asset" },
  { key: "chain", header: "Chain" },
  { key: "classification", header: "Class" },
  { key: "quantity", header: "Quantity", align: "right" },
  { key: "price_usd", header: "Price", align: "right" },
  { key: "value_usd", header: "Value", align: "right" },
  { key: "portfolio_ratio", header: "Weight", align: "right" },
];

export default function AssetExplorer({ holdings, riskAssets }) {
  const [selectedKey, setSelectedKey] = useState(
    () => `${holdings[0].symbol}-${holdings[0].network}`
  );
  const [history, setHistory] = useState(null);
  const [historyState, setHistoryState] = useState("loading");

  const selected =
    holdings.find((h) => `${h.symbol}-${h.network}` === selectedKey) ?? holdings[0];

  // Risk figures are computed per symbol, aggregated across chains.
  const assetRisk = riskAssets.find((asset) => asset.symbol === selected.symbol);

  const requestRef = useRef(null);

  useEffect(() => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;

    setHistoryState("loading");
    setHistory(null);

    // Unknown tokens are priced by contract address: their symbol may collide
    // with an unrelated asset on the pricing service.
    const query =
      selected.classification === "unknown" && selected.contract_address
        ? { network: selected.network, address: selected.contract_address }
        : { symbol: selected.symbol };

    fetchPriceHistory({ ...query, days: 180, signal: controller.signal })
      .then((data) => {
        if (controller.signal.aborted) return;
        setHistory(data);
        setHistoryState(data.points?.length >= 2 ? "ready" : "empty");
      })
      .catch((error) => {
        if (error.name === "AbortError") return;
        setHistoryState("empty");
      });

    return () => controller.abort();
  }, [selected.symbol, selected.network, selected.classification, selected.contract_address]);

  useEffect(() => () => requestRef.current?.abort(), []);

  const renderCell = (holding, column) => {
    switch (column.key) {
      case "symbol":
        return (
          <span className={styles.assetCell}>
            <span className={styles.assetSymbol}>{holding.symbol}</span>
            {holding.name && holding.name !== holding.symbol && (
              <span className={styles.assetName}>{holding.name}</span>
            )}
          </span>
        );
      case "classification":
        return <span className={styles.txType}>{holding.classification}</span>;
      case "quantity":
        return quantity(holding.quantity);
      case "price_usd":
        return usd(holding.price_usd, {
          decimals: holding.price_usd < 1 ? 6 : holding.price_usd < 10 ? 4 : 2,
        });
      case "value_usd":
        return usd(holding.value_usd, { decimals: 0 });
      case "portfolio_ratio":
        return ratio(holding.portfolio_ratio, { decimals: 2 });
      default:
        return holding[column.key];
    }
  };

  return (
    <div className={`${styles.grid} ${styles.splitWide}`}>
      <Panel title="Holdings" meta="Select a row for detail" flush>
        <Table
          columns={COLUMNS}
          rows={holdings}
          rowKey={(holding) => `${holding.symbol}-${holding.network}`}
          renderCell={renderCell}
          onRowSelect={(holding) =>
            setSelectedKey(`${holding.symbol}-${holding.network}`)
          }
          selectedKey={selectedKey}
        />
      </Panel>

      <div className={styles.stackWide}>
        <Panel
          title={`${selected.symbol} detail`}
          meta={`${selected.chain} · ${selected.classification}`}
        >
          <div className={styles.stack}>
            <div className={styles.dualStat}>
              <Stat
                label="Position value"
                value={usd(selected.value_usd, { decimals: 0 })}
                note={quantity(selected.quantity, selected.symbol)}
                emphasis
              />
              <Stat
                label="Price"
                value={usd(selected.price_usd, {
                  decimals: selected.price_usd < 1 ? 6 : 2,
                })}
                note="Live from Alchemy"
              />
            </div>

            <dl className={styles.defs}>
              <div className={styles.def}>
                <dt>Portfolio weight</dt>
                <dd>{ratio(selected.portfolio_ratio, { decimals: 2 })}</dd>
              </div>
              <div className={styles.def}>
                <dt>Classification</dt>
                <dd>{selected.classification}</dd>
              </div>
              <div className={styles.def}>
                <dt>Network</dt>
                <dd>{selected.chain}</dd>
              </div>
              {assetRisk ? (
                <>
                  <div className={styles.def}>
                    <dt>Annualised volatility</dt>
                    <dd>{ratio(assetRisk.annual_volatility)}</dd>
                  </div>
                  <div className={styles.def}>
                    <dt>Beta to portfolio</dt>
                    <dd>{assetRisk.beta_to_portfolio.toFixed(2)}</dd>
                  </div>
                  <div className={styles.def}>
                    <dt>Worst drawdown</dt>
                    <dd>{ratio(assetRisk.max_drawdown)}</dd>
                  </div>
                </>
              ) : (
                <div className={styles.def}>
                  <dt>Risk model</dt>
                  <dd>Excluded — not enough history</dd>
                </div>
              )}
              {selected.contract_address && (
                <div className={styles.def}>
                  <dt>Contract</dt>
                  <dd className={styles.address}>{selected.contract_address}</dd>
                </div>
              )}
            </dl>

            {assetRisk && (
              <Meter
                label="Risk contribution"
                value={Math.max(assetRisk.risk_contribution * 100, 0)}
                display={ratio(assetRisk.risk_contribution)}
              />
            )}
          </div>
        </Panel>

        <Panel title="Price history" meta={`${selected.symbol} · 180 days`}>
          {historyState === "loading" && <Loading label="Fetching price history" />}
          {historyState === "empty" && (
            <Empty
              title="No price history"
              detail="The pricing service has no daily series for this token."
            />
          )}
          {historyState === "ready" && (
            <LineChart
              series={history.points.map((point) => ({
                t: point.timestamp,
                v: point.value,
              }))}
              height={200}
              formatValue={(value) =>
                usd(value, {
                  compact: value >= 1000,
                  decimals: value < 1 ? 4 : 0,
                })
              }
            />
          )}
        </Panel>
      </div>
    </div>
  );
}
