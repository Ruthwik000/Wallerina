"use client";

import PageHeader from "@/components/PageHeader";
import PageState from "@/components/PageState";
import { useWallet } from "@/components/WalletProvider";
import SimulationRunner from "./SimulationRunner";

export default function SimulationsPage() {
  const { address, simulation, scenarios, portfolio } = useWallet();

  const header = (
    <PageHeader
      eyebrow="Analysis"
      title="Simulations"
      description="Monte Carlo over the wallet's live holdings, driven by correlated shocks estimated from their own price history."
    />
  );

  return (
    <PageState header={header} loadingLabel="Preparing the simulation">
      {() => (
        <SimulationRunner
          address={address}
          initial={simulation}
          scenarios={scenarios ?? []}
          hasStablecoin={portfolio.stablecoin_value_usd > 0}
        />
      )}
    </PageState>
  );
}
