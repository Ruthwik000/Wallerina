"use client";

import Chat from "@/components/Chat";
import PageHeader from "@/components/PageHeader";
import { Disconnected, ErrorState, Loading } from "@/components/States";
import { useWallet } from "@/components/WalletProvider";

export default function ChatPage() {
  const { connected, restored, status, error, refresh } = useWallet();

  if (!restored) return null;
  if (!connected) return <Disconnected />;

  return (
    <>
      <PageHeader
        eyebrow="Assistant"
        title="Ask"
        description="Questions about this wallet, answered from the figures the risk engine has computed for it."
      />

      {status === "loading" && (
        <Loading
          label="Loading your portfolio"
          detail="The assistant needs the wallet's analysis before it can answer."
        />
      )}
      {status === "error" && <ErrorState error={error} onRetry={refresh} />}
      {status === "ready" && <Chat />}
    </>
  );
}
