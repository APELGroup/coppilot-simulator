/**
 * Reactive store for simulation scenarios.
 *
 * Scenarios are persisted in PostgreSQL via the backend; this store keeps an
 * in-memory copy that React components can subscribe to via `useScenarios()`.
 * Falls back gracefully when the DB is unavailable.
 */
import { useSyncExternalStore } from "react";
import { fetchScenarios, createScenarioApi, deleteScenarioApi, type ScenarioApi } from "./api";
import type { Scenario } from "./mock-data";

const EVENT = "dtlab-scenarios-change";

// ── In-memory state ────────────────────────────────────────────────────────────

let _scenarios: Scenario[] = [];

function emit() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(EVENT));
}

// ── Subscription (useSyncExternalStore) ────────────────────────────────────────

function subscribe(cb: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(EVENT, cb);
  return () => window.removeEventListener(EVENT, cb);
}

function getSnapshot(): Scenario[] {
  return _scenarios;
}

// ── Public accessors ───────────────────────────────────────────────────────────

/** React hook — re-renders whenever the store changes. */
export function useScenarios(): Scenario[] {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

/** Synchronous read for non-React callers (runs-store, results page, etc.). */
export function getAllScenarios(): Scenario[] {
  return _scenarios;
}

// ── Conversion ─────────────────────────────────────────────────────────────────

function apiToScenario(s: ScenarioApi): Scenario {
  return {
    id: s.id,
    name: s.name,
    networkId: s.networkId,
    simType: (s.simType as Scenario["simType"]) ?? "time_series",
    mode: (s.mode as Scenario["mode"]) ?? "balanced",
    horizon: s.horizon,
    timestep: s.timestep ?? "—",
    createdBy: s.createdBy,
    createdAt: s.createdAt,
  };
}

// ── Bootstrap ──────────────────────────────────────────────────────────────────

/**
 * Fetch all scenarios from the backend and populate the store.
 * Called once at app startup (from __root.tsx) and after login.
 * Silently no-ops when DB is unavailable.
 */
export async function seedScenariosFromBackend(): Promise<void> {
  try {
    const data = await fetchScenarios();
    _scenarios = data.map(apiToScenario);
    emit();
  } catch {
    // DB unavailable or not authenticated yet — keep existing data
  }
}

// ── Mutations ──────────────────────────────────────────────────────────────────

/**
 * Persist a new scenario to the backend and add it to the store.
 * Optimistically prepends it to the local list; replaces with the server
 * response on success, or keeps the local copy when DB is unavailable.
 */
export async function createScenario(input: Scenario): Promise<void> {
  // Optimistic update
  _scenarios = [input, ..._scenarios];
  emit();

  try {
    const saved = await createScenarioApi({
      id: input.id,
      name: input.name,
      networkId: input.networkId,
      simType: input.simType,
      mode: input.mode,
      horizon: input.horizon,
      timestep: input.timestep || "15min",
      createdBy: input.createdBy,
    });
    // Replace local copy with the canonical server record
    _scenarios = _scenarios.map((s) =>
      s.id === input.id ? apiToScenario(saved) : s,
    );
    emit();
  } catch {
    // Keep optimistic copy — DB unavailable
  }
}

/**
 * Delete a scenario from the backend and remove it from the store.
 */
export async function removeScenario(id: string): Promise<void> {
  try {
    await deleteScenarioApi(id);
  } catch {
    // DB unavailable — remove from memory anyway
  }
  _scenarios = _scenarios.filter((s) => s.id !== id);
  emit();
}
