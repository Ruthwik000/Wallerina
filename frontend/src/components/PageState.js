"use client";

import { Disconnected, ErrorState, Loading } from "./States";
import { useWallet } from "./WalletProvider";

/**
 * Gate for every data-backed page.
 *
 * Renders the shared disconnected / loading / error states and only calls
 * `children` once real data is present, so no page has to defend against
 * a null portfolio.
 */
export default function PageState({ children, header = null, loadingLabel }) {
  const { connected, restored, status, error, refresh } = useWallet();

  // Nothing is known until localStorage has been read; rendering "not
  // connected" first would flash for anyone with a saved wallet.
  if (!restored) return null;

  if (!connected) {
    return (
      <>
        {header}
        <Disconnected />
      </>
    );
  }

  if (status === "loading" || status === "idle") {
    return (
      <>
        {header}
        <Loading
          label={loadingLabel ?? "Reading the blockchain"}
          detail="Scanning balances across Ethereum, Base, Arbitrum and Polygon, then pricing them and estimating risk. The first read of a wallet takes around twenty seconds."
        />
      </>
    );
  }

  if (status === "error") {
    return (
      <>
        {header}
        <ErrorState error={error} onRetry={refresh} />
      </>
    );
  }

  return (
    <>
      {header}
      {children()}
    </>
  );
}
