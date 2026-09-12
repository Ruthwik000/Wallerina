"use client";

import { useEffect, useState } from "react";
import { fetchGoalPresets } from "@/lib/api";
import styles from "./GoalPicker.module.css";

/* Mirrors the backend's preset table so the choices render instantly; the
   live list replaces it once fetched. Labels resolve with no model call. */
export const FALLBACK_PRESETS = [
  { id: "aggressive_growth", label: "Make heavy profit fast", description: "Maximum upside. Accepts large swings and deep losses.", maximum_drawdown: 0.35 },
  { id: "growth", label: "Grow steadily", description: "Grow the portfolio while accepting meaningful volatility.", maximum_drawdown: 0.28 },
  { id: "balanced", label: "Balanced", description: "Growth with real protection against losses.", maximum_drawdown: 0.2 },
  { id: "save_over_time", label: "Save over time", description: "Accumulate steadily; losses are unwelcome.", maximum_drawdown: 0.15 },
  { id: "capital_preservation", label: "Preserve capital", description: "Protecting what you already have comes first.", maximum_drawdown: 0.1 },
];

export function matchPreset(presets, goal) {
  const normalised = (goal ?? "").trim().toLowerCase();
  if (!normalised) return null;
  return presets.find((preset) => preset.label.toLowerCase() === normalised || preset.id === normalised) ?? null;
}

/**
 * Preset goals plus a free-text option. Reports the chosen goal text through
 * `onChange`; an empty string means nothing usable is chosen yet.
 */
export default function GoalPicker({ initialValue = "", onChange, idPrefix = "goal" }) {
  const initialMatch = matchPreset(FALLBACK_PRESETS, initialValue);
  const [presets, setPresets] = useState(FALLBACK_PRESETS);
  const [selected, setSelected] = useState(
    initialMatch ? initialMatch.id : initialValue.trim() ? "custom" : null
  );
  const [custom, setCustom] = useState(initialMatch ? "" : initialValue);

  useEffect(() => {
    const controller = new AbortController();
    fetchGoalPresets({ signal: controller.signal })
      .then((list) => {
        if (Array.isArray(list) && list.length) setPresets(list);
      })
      .catch(() => {
        // The built-in list is already showing.
      });
    return () => controller.abort();
  }, []);

  const choosePreset = (preset) => {
    setSelected(preset.id);
    onChange(preset.label);
  };

  const chooseCustom = () => {
    setSelected("custom");
    onChange(custom);
  };

  return (
    <div className={styles.picker}>
      <div className={styles.options} role="radiogroup" aria-label="Goal">
        {presets.map((preset) => {
          const active = selected === preset.id;
          return (
            <button
              key={preset.id}
              type="button"
              role="radio"
              aria-checked={active}
              className={`${styles.option} ${active ? styles.optionActive : ""}`}
              onClick={() => choosePreset(preset)}
            >
              <span className={styles.optionHead}>
                <span className={styles.optionLabel}>{preset.label}</span>
                {preset.maximum_drawdown != null && (
                  <span className={styles.optionMeta}>
                    Max loss {Math.round(preset.maximum_drawdown * 100)}%
                  </span>
                )}
              </span>
              <span className={styles.optionDescription}>{preset.description}</span>
            </button>
          );
        })}

        <button
          type="button"
          role="radio"
          aria-checked={selected === "custom"}
          className={`${styles.option} ${selected === "custom" ? styles.optionActive : ""}`}
          onClick={chooseCustom}
        >
          <span className={styles.optionHead}>
            <span className={styles.optionLabel}>In my own words</span>
          </span>
          <span className={styles.optionDescription}>
            Describe what the money is for, your horizon or the largest loss you would accept.
          </span>
        </button>
      </div>

      {selected === "custom" && (
        <div className={styles.custom}>
          <label className={styles.label} htmlFor={`${idPrefix}-custom`}>
            Your goal
          </label>
          <textarea
            id={`${idPrefix}-custom`}
            className={styles.textarea}
            rows={3}
            maxLength={500}
            placeholder="e.g. I'm saving for a house in six months and can't lose more than 15%"
            value={custom}
            onChange={(event) => {
              setCustom(event.target.value);
              onChange(event.target.value);
            }}
            autoFocus
          />
          <p className={styles.hint}>
            The goal agent reads this into a goal type, loss limit and horizon. The
            allocation itself is still set by the engine.
          </p>
        </div>
      )}
    </div>
  );
}
