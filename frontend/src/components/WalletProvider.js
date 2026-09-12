"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { fetchAnalysis, isValidAddress } from "@/lib/api";

const STORAGE_KEY = "wallerina.wallet";

const WalletContext = createContext(null);

/**
 * Holds the connected wallet and the analysis fetched for it.
 *
 * A full analysis costs the backend 20+ provider calls, so it is fetched once
 * here and shared by every page rather than re-requested on navigation.
 */
export function WalletProvider({ children }) {
  const [address, setAddress] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [status, setStatus] = useState("idle"); // idle | loading | ready | error
  const [error, setError] = useState(null);
  const [restored, setRestored] = useState(false);

  // Lets an in-flight request be abandoned when the wallet changes.
  const requestRef = useRef(null);

  // Restore the previous session on mount. Reading localStorage during render
  // would break hydration, so it happens in an effect.
  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (saved && isValidAddress(saved)) setAddress(saved);
    } catch {
      // Private mode or blocked storage; start disconnected.
    }
    setRestored(true);
  }, []);

  const load = useCallback(async (target, { refresh = false } = {}) => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;

    setStatus("loading");
    setError(null);

    try {
      const data = await fetchAnalysis(target, { refresh, signal: controller.signal });
      if (controller.signal.aborted) return;
      setAnalysis(data);
      setStatus("ready");
    } catch (failure) {
      if (failure.name === "AbortError") return;
      setAnalysis(null);
      setError(failure);
      setStatus("error");
    }
  }, []);

  // Fetch whenever the connected wallet changes.
  useEffect(() => {
    if (!restored) return;

    if (!address) {
      setAnalysis(null);
      setStatus("idle");
      return;
    }

    load(address);
  }, [address, restored, load]);

  useEffect(() => () => requestRef.current?.abort(), []);

  const connect = useCallback((value) => {
    const trimmed = value.trim();
    if (!isValidAddress(trimmed)) {
      throw new Error("Enter a valid 42-character address starting with 0x");
    }
    try {
      window.localStorage.setItem(STORAGE_KEY, trimmed);
    } catch {
      // Non-persistent session is still usable.
    }
    setAddress(trimmed);
    return trimmed;
  }, []);

  const disconnect = useCallback(() => {
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      // Nothing to clean up.
    }
    requestRef.current?.abort();
    setAddress(null);
    setAnalysis(null);
    setError(null);
    setStatus("idle");
  }, []);

  const refresh = useCallback(() => {
    if (address) load(address, { refresh: true });
  }, [address, load]);

  const value = useMemo(
    () => ({
      address,
      analysis,
      status,
      error,
      restored,
      connected: Boolean(address),
      // Convenience accessors so pages don't reach through `analysis` each time.
      portfolio: analysis?.portfolio ?? null,
      risk: analysis?.risk ?? null,
      simulation: analysis?.simulation ?? null,
      scenarios: analysis?.scenarios ?? null,
      marketStress: analysis?.market_stress ?? null,
      excluded: analysis?.excluded_from_analysis ?? [],
      connect,
      disconnect,
      refresh,
    }),
    [address, analysis, status, error, restored, connect, disconnect, refresh]
  );

  return <WalletContext.Provider value={value}>{children}</WalletContext.Provider>;
}

export function useWallet() {
  const context = useContext(WalletContext);
  if (context === null) {
    throw new Error("useWallet must be used inside a WalletProvider");
  }
  return context;
}
