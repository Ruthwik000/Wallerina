import PageHeader from "@/components/PageHeader";
import Panel from "@/components/Panel";
import Stat from "@/components/Stat";
import Meter from "@/components/Meter";
import Table from "@/components/Table";
import Donut from "@/components/charts/Donut";
import { assets, portfolio, priceHistory, transactions } from "@/lib/data";
import { dateLabel, percent, quantity, usd } from "@/lib/format";
import AssetExplorer from "./AssetExplorer";
import styles from "../page.module.css";

export const metadata = { title: "Portfolio · Wallerina" };

const TX_COLUMNS = [
  { key: "date", header: "Date" },
  { key: "type", header: "Type" },
  { key: "asset", header: "Asset" },
  { key: "quantity", header: "Quantity", align: "right" },
  { key: "value", header: "Value", align: "right" },
  { key: "chain", header: "Chain", align: "right" },
];

export default function PortfolioPage() {
  const stablecoins = assets.filter((asset) => asset.class === "stablecoin");

  return (
    <>
      <PageHeader
        eyebrow="Overview"
        title="Portfolio"
        description="Every position across connected networks, with the price history and risk contribution behind each one."
      />

      <div className={`${styles.statRow} ${styles.statRow4}`}>
        <Stat
          label="Total portfolio value"
          value={usd(portfolio.totalValue, { decimals: 0 })}
          delta={portfolio.change24h}
          deltaLabel={`${percent(portfolio.change24h, { sign: true, decimals: 2 })} 24h`}
          size="lg"
          emphasis
        />
        <Stat
          label="Positions"
          value={`${assets.length}`}
          note={`${portfolio.chains.length} networks`}
          size="lg"
        />
        <Stat
          label="Stablecoin holdings"
          value={usd(portfolio.stablecoinValue, { decimals: 0 })}
          note={`${percent(portfolio.stablecoinRatio)} of book`}
          size="lg"
        />
        <Stat
          label="Cost basis"
          value={usd(portfolio.costBasis, { decimals: 0 })}
          delta={portfolio.totalReturnPct}
          deltaLabel={`${percent(portfolio.totalReturnPct, { sign: true })} realised + unrealised`}
          size="lg"
        />
      </div>

      <AssetExplorer
        assets={assets}
        totalValue={portfolio.totalValue}
        priceHistory={priceHistory}
      />

      <div className={`${styles.grid} ${styles.cols3}`}>
        <Panel title="Asset allocation" meta="By share of total value">
          <Donut
            segments={portfolio.allocation}
            caption={`${assets.length}`}
            captionLabel="Positions"
          />
        </Panel>

        <Panel title="Chain breakdown" meta="Value by network">
          <div className={styles.stack}>
            {portfolio.chains.map((chain) => (
              <Meter
                key={chain.chain}
                label={chain.chain}
                value={chain.weight}
                display={`${percent(chain.weight)} · ${usd(chain.value, { compact: true })}`}
              />
            ))}
          </div>
        </Panel>

        <Panel title="Stablecoin holdings" meta="Peg exposure by issuer">
          <dl className={styles.defs}>
            {stablecoins.map((coin) => (
              <div key={coin.symbol} className={styles.def}>
                <dt>
                  {coin.symbol} · {coin.chain}
                </dt>
                <dd>{usd(coin.value, { decimals: 0 })}</dd>
              </div>
            ))}
            <div className={`${styles.def} ${styles.defStrong}`}>
              <dt>Total</dt>
              <dd>{usd(portfolio.stablecoinValue, { decimals: 0 })}</dd>
            </div>
          </dl>
        </Panel>
      </div>

      <Panel title="Transaction history" meta="Last 40 days" flush>
        <Table
          columns={TX_COLUMNS}
          rows={transactions}
          rowKey={(tx) => tx.id}
          renderCell={(tx, column) => {
            switch (column.key) {
              case "date":
                return dateLabel(tx.date);
              case "quantity":
                return quantity(tx.quantity);
              case "value":
                return usd(tx.value, { decimals: 0 });
              case "type":
                return <span className={styles.txType}>{tx.type}</span>;
              default:
                return tx[column.key];
            }
          }}
        />
      </Panel>
    </>
  );
}
