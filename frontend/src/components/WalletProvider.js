"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { fetchAnalysis, fetchGoal, isValidAddress, saveGoal } from "@/lib/api";

const STORAGE_KEY = "wallerina.wallet";
const GOAL_PREFIX = "wallerina.goal.";

const WalletContext = createContext(null);

function readStoredGoal(address) {
  try {
    return window.localStorage.getItem(GOAL_PREFIX + address.toLowerCase());
  } catch {
    // Blocked storage; the backend copy is still fetched.
    return null;
  }
}

function writeStoredGoal(address, goal) {
  try {
    window.localStorage.setItem(GOAL_PREFIX + address.toLowerCase(), goal);
  } catch {
    // Non-persistent session is still usable.
  }
}

/**
 * Holds the connected wallet, its goal and the analysis fetched for it.
 *
 * A full analysis costs the backend 20+ provider calls, so it is fetched once
 * here and shared by every page rather than re-requested on navigation.
 *
 * The goal is kept per wallet in localStorage for an instant first render and
 * saved to the backend, which persists it in the database when one is set up.
 */
export function WalletProvider({ children }) {
  const [address, setAddress] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [status, setStatus] = useState("idle"); // idle | loading | ready | error
  const [error, setError] = useState(null);
  const [restored, setRestored] = useState(false);

  const [goal, setGoalState] = useState(null);
  const [goalStatus, setGoalStatus] = useState("idle"); // idle | loading | ready
  const [goalPersisted, setGoalPersisted] = useState(false);

  // Lets an in-flight request be abandoned when the wallet changes.
  const requestRef = useRef(null);
  // Wallets whose goal was chosen in this session; a slower backend read must
  // not overwrite that choice with an older saved goal.
  const goalsChosenHere = useRef(new Set());

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

  // Load the wallet's goal: local copy first, then the backend's.
  useEffect(() => {
    if (!restored) return undefined;

    if (!address) {
      setGoalState(null);
      setGoalStatus("idle");
      setGoalPersisted(false);
      return undefined;
    }

    const key = address.toLowerCase();
    const controller = new AbortController();
    setGoalState(readStoredGoal(address));
    setGoalStatus("loading");

    fetchGoal(address, { signal: controller.signal })
      .then((saved) => {
        if (goalsChosenHere.current.has(key)) return;
        if (saved?.goal) {
          setGoalState(saved.goal);
          setGoalPersisted(Boolean(saved.persisted));
          writeStoredGoal(address, saved.goal);
        }
      })
      .catch(() => {
        // Backend unreachable: the local copy stands.
      })
      .finally(() => {
        if (!controller.signal.aborted) setGoalStatus("ready");
      });

    return () => controller.abort();
  }, [address, restored]);

  useEffect(() => () => requestRef.current?.abort(), []);

  const persistGoal = useCallback(async (target, text) => {
    goalsChosenHere.current.add(target.toLowerCase());
    writeStoredGoal(target, text);
    try {
      const saved = await saveGoal(target, text);
      setGoalPersisted(Boolean(saved?.persisted));
      return Boolean(saved?.persisted);
    } catch {
      setGoalPersisted(false);
      return false;
    }
  }, []);

  const connect = useCallback(
    (value, { goal: chosenGoal } = {}) => {
      const trimmed = value.trim();
      if (!isValidAddress(trimmed)) {
        throw new Error("Enter a valid 42-character address starting with 0x");
      }
      try {
        window.localStorage.setItem(STORAGE_KEY, trimmed);
      } catch {
        // Non-persistent session is still usable.
      }
      if (chosenGoal) {
        setGoalState(chosenGoal);
        persistGoal(trimmed, chosenGoal);
      }
      setAddress(trimmed);
      return trimmed;
    },
    [persistGoal]
  );

  const setGoal = useCallback(
    async (text) => {
      if (!address || !text) return false;
      setGoalState(text);
      return persistGoal(address, text);
    },
    [address, persistGoal]
  );

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
    setGoalState(null);
    setGoalStatus("idle");
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
      goal,
      goalStatus,
      goalPersisted,
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
      setGoal,
    }),
    [address, analysis, status, error, restored, goal, goalStatus, goalPersisted, connect, disconnect, refresh, setGoal]
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
