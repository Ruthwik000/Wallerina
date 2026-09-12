"use client";

import { useState } from "react";
import Meter from "@/components/Meter";
import Panel from "@/components/Panel";
import Stat from "@/components/Stat";
import Table from "@/components/Table";
import LineChart from "@/components/charts/LineChart";
import { percent, quantity, usd } from "@/lib/format";
import styles from "../page.module.css";

const COLUMNS = [
  { key: "symbol", header: "Asset" },
  { key: "chain", header: "Chain" },
  { key: "quantity", header: "Quantity", align: "right" },
  { key: "price", header: "Price", align: "right" },
  { key: "value", header: "Value", align: "right" },
  { key: "weight", header: "Weight", align: "right" },
  { key: "change24h", header: "24h", align: "right" },
  { key: "change30d", header: "30d", align: "right" },
  { key: "riskContribution", header: "Risk", align: "right" },
];

/* Table and detail panel are one unit: selecting a row drives the panel, the
   price chart and the risk readout beside it. */
export default function AssetExplorer({ assets, totalValue, priceHistory }) {
  const [selectedSymbol, setSelectedSymbol] = useState(assets[0].symbol);
  const selected = assets.find((asset) => asset.symbol === selectedSymbol);

  const renderCell = (asset, column) => {
    switch (column.key) {
      case "symbol":
        return (
          <span className={styles.assetCell}>
            <span className={styles.assetSymbol}>{asset.symbol}</span>
            <span className={styles.assetName}>{asset.name}</span>
          </span>
        );
      case "quantity":
        return quantity(asset.quantity);
      case "price":
        return usd(asset.price, { decimals: asset.price < 10 ? 4 : 2 });
      case "value":
        return usd(asset.value, { decimals: 0 });
      case "weight":
        return percent((asset.value / totalValue) * 100);
      case "change24h":
      case "change30d":
        return (
          <span className={asset[column.key] < 0 ? styles.negative : styles.positive}>
            {percent(asset[column.key], { sign: true, decimals: 2 })}
          </span>
        );
      case "riskContribution":
        return percent(asset.riskContribution);
      default:
        return asset[column.key];
    }
  };

  return (
    <div className={`${styles.grid} ${styles.splitWide}`}>
      <Panel title="Assets" meta="Select a row for detail" flush>
        <Table
          columns={COLUMNS}
          rows={assets}
          rowKey={(asset) => asset.symbol}
          renderCell={renderCell}
          onRowSelect={(asset) => setSelectedSymbol(asset.symbol)}
          selectedKey={selectedSymbol}
        />
      </Panel>

      <div className={styles.stackWide}>
        <Panel title={`${selected.name} detail`} meta={`${selected.symbol} · ${selected.chain}`}>
          <div className={styles.stack}>
            <div className={styles.dualStat}>
              <Stat
                label="Position value"
                value={usd(selected.value, { decimals: 0 })}
                note={quantity(selected.quantity, selected.symbol)}
                emphasis
              />
              <Stat
                label="Price"
                value={usd(selected.price, { decimals: selected.price < 10 ? 4 : 2 })}
                delta={selected.change24h}
                deltaLabel={`${percent(selected.change24h, { sign: true, decimals: 2 })} 24h`}
              />
            </div>

            <dl className={styles.defs}>
              <div className={styles.def}>
                <dt>Portfolio weight</dt>
                <dd>{percent((selected.value / totalValue) * 100)}</dd>
              </div>
              <div className={styles.def}>
                <dt>30 day performance</dt>
                <dd>{percent(selected.change30d, { sign: true, decimals: 2 })}</dd>
              </div>
              <div className={styles.def}>
                <dt>Annualised volatility</dt>
                <dd>{percent(selected.volatility)}</dd>
              </div>
              <div className={styles.def}>
                <dt>Beta to portfolio</dt>
                <dd>{selected.beta.toFixed(2)}</dd>
              </div>
              <div className={styles.def}>
                <dt>Classification</dt>
                <dd>{selected.class === "stablecoin" ? "Stablecoin" : "Volatile"}</dd>
              </div>
            </dl>

            <Meter
              label="Risk contribution"
              value={selected.riskContribution}
              display={percent(selected.riskContribution)}
            />
          </div>
        </Panel>

        <Panel title="Historical price" meta={`${selected.symbol} · 90 days`}>
          <LineChart
            series={priceHistory[selected.symbol]}
            height={200}
            formatValue={(value) =>
              usd(value, { compact: value >= 1000, decimals: value < 10 ? 3 : 0 })
            }
          />
        </Panel>
      </div>
    </div>
  );
}
