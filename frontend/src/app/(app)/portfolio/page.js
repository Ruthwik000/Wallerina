"use client";

import Meter from "@/components/Meter";
import PageHeader from "@/components/PageHeader";
import PageState from "@/components/PageState";
import Panel from "@/components/Panel";
import Stat from "@/components/Stat";
import { Empty, Notice } from "@/components/States";
import { useWallet } from "@/components/WalletProvider";
import Donut from "@/components/charts/Donut";
import { ratio, usd } from "@/lib/format";
import AssetExplorer from "./AssetExplorer";
import styles from "../page.module.css";

export default function PortfolioPage() {
  const { portfolio, risk } = useWallet();

  const header = (
    <PageHeader
      eyebrow="Overview"
      title="Portfolio"
      description="Every priced position the wallet holds across supported networks, with its price history and risk contribution."
    />
  );

  return (
    <PageState header={header}>
      {() => {
        const stablecoins = portfolio.holdings.filter(
          (holding) => holding.classification === "stablecoin"
        );
        const unknown = portfolio.holdings.filter(
          (holding) => holding.classification === "unknown"
        );

        if (portfolio.holdings.length === 0) {
          return (
            <Empty
              title="No priced holdings"
              detail="This wallet has no positions with a live price above the dust threshold. Spam airdrops and unpriced tokens are filtered out before analysis."
            />
          );
        }

        return (
          <>
            <div className={`${styles.statRow} ${styles.statRow4}`}>
              <Stat
                label="Total value"
                value={usd(portfolio.total_value_usd, { decimals: 0 })}
                size="lg"
                emphasis
              />
              <Stat
                label="Positions kept"
                value={`${portfolio.holdings_kept}`}
                note={`Filtered from ${portfolio.holdings_scanned.toLocaleString("en-US")} tokens scanned`}
                size="lg"
              />
              <Stat
                label="Stablecoin holdings"
                value={usd(portfolio.stablecoin_value_usd, { decimals: 0 })}
                note={`${ratio(portfolio.stablecoin_ratio)} of book`}
                size="lg"
              />
              <Stat
                label="Concentration"
                value={portfolio.concentration.toFixed(3)}
                note="HHI — 1.0 is a single asset"
                size="lg"
              />
            </div>

            {portfolio.scan_truncated && (
              <Notice>
                The page limit was reached before this wallet was fully scanned,
                so holdings and totals may be understated.
              </Notice>
            )}

            <AssetExplorer holdings={portfolio.holdings} riskAssets={risk.assets} />

            <div className={`${styles.grid} ${styles.cols3}`}>
              <Panel title="Allocation" meta="Top positions by value">
                <Donut
                  segments={portfolio.holdings.slice(0, 8).map((holding) => ({
                    id: `${holding.network}:${holding.contract_address ?? "native"}`,
                    symbol: holding.symbol,
                    weight: holding.portfolio_ratio * 100,
                  }))}
                  caption={`${portfolio.holdings_kept}`}
                  captionLabel="Positions"
                />
              </Panel>

              <Panel title="Chain breakdown" meta="Value by network">
                <div className={styles.stack}>
                  {portfolio.chains.map((chain) => (
                    <Meter
                      key={chain.network}
                      label={chain.chain}
                      value={chain.ratio * 100}
                      display={`${ratio(chain.ratio)} · ${usd(chain.value_usd, { compact: true })}`}
                    />
                  ))}
                </div>
              </Panel>

              <Panel title="Stablecoin holdings" meta="Recognised pegs only">
                {stablecoins.length === 0 ? (
                  <p className={styles.helper}>
                    No recognised stablecoin in this wallet. Classification is by
                    contract address, so a token is never assumed to be a
                    stablecoin from its name.
                  </p>
                ) : (
                  <dl className={styles.defs}>
                    {stablecoins.map((coin) => (
                      <div key={`${coin.symbol}-${coin.network}`} className={styles.def}>
                        <dt>
                          {coin.symbol} · {coin.chain}
                        </dt>
                        <dd>{usd(coin.value_usd, { decimals: 0 })}</dd>
                      </div>
                    ))}
                    <div className={`${styles.def} ${styles.defStrong}`}>
                      <dt>Total</dt>
                      <dd>{usd(portfolio.stablecoin_value_usd, { decimals: 0 })}</dd>
                    </div>
                  </dl>
                )}
              </Panel>
            </div>

            {unknown.length > 0 && (
              <Panel
                title="Unrecognised assets"
                meta={`${unknown.length} positions · ${usd(portfolio.unknown_value_usd, { compact: true })}`}
              >
                <p className={styles.helper}>
                  These tokens are not in the trusted asset registry, so they are
                  classified as unknown rather than guessed at. They are counted
                  as volatile exposure — treating an unrecognised token as safe
                  is the one error the classifier must never make.
                </p>
                <dl className={styles.defs}>
                  {unknown.slice(0, 10).map((holding) => (
                    <div key={`${holding.symbol}-${holding.network}`} className={styles.def}>
                      <dt>
                        {holding.symbol} · {holding.chain}
                      </dt>
                      <dd>{usd(holding.value_usd, { decimals: 0 })}</dd>
                    </div>
                  ))}
                </dl>
              </Panel>
            )}

            <Panel title="Transaction history" meta="Not yet available">
              <p className={styles.helper}>
                Wallerina reads current balances, not transfer history. Showing
                transactions needs a separate indexing endpoint, which the backend
                does not implement yet.
              </p>
            </Panel>
          </>
        );
      }}
    </PageState>
  );
}
