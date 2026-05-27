// Reactive store over the in-memory `runs` array. Mutations keep the static
// `runs` export in sync for any code that imports it directly.
import { useSyncExternalStore } from "react";
import {
  runs as runsArray,
  networks,
  type Run,
} from "./mock-data";
import { getAllScenarios } from "./scenarios-store";
import { fetchRuns, deleteRunApi } from "./api";
import { removeScenario } from "./scenarios-store";
import { parseRunId } from "./run-context";

type Listener = () => void;
const listeners = new Set<Listener>();
let runsSnapshot: Run[] = [...runsArray];

function emit() {
  runsSnapshot = [...runsArray];
  listeners.forEach((l) => l());
}

function subscribe(l: Listener) {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}

function getSnapshot() {
  return runsSnapshot;
}

export function useRuns(): Run[] {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

export function getAllRuns(): Run[] {
  return runsSnapshot;
}

/**
 * Fetch all completed runs from the backend (scans data/results/ on disk)
 * and merge them into the in-memory store. Safe to call multiple times —
 * duplicate ids are skipped. Call this once on app startup.
 */
export async function seedRunsFromBackend(): Promise<void> {
  try {
    const backendRuns = await fetchRuns();
    if (!backendRuns.length) return;

    const existingIds = new Set(runsArray.map((r) => r.id));
    const allNetworks = networks;

    for (const br of backendRuns) {
      if (existingIds.has(br.run_id)) continue;

      const net = allNetworks.find((n) => n.id === br.network_id);
      const parsed = parseRunId(br.run_id);

      const horizonLabel = parsed
        ? parsed.horizon.charAt(0).toUpperCase() + parsed.horizon.slice(1)
        : null;
      const dateLabel = parsed
        ? parsed.horizon === "month"
          ? `${parsed.year}-${String(parsed.month).padStart(2, "0")}`
          : `${parsed.year}-${String(parsed.month).padStart(2, "0")}-${String(parsed.day).padStart(2, "0")}`
        : br.run_id;

      const run: Run & { networkId: string; createdBy?: string } = {
        id: br.run_id,
        scenarioId: "",
        scenarioName: horizonLabel ? `${horizonLabel} · ${dateLabel}` : br.run_id,
        networkName: net?.name ?? br.network_id,
        networkId: br.network_id,
        status: "completed",
        startedAt: br.started_at ? fmtStartedAt(br.started_at) : "—",
        duration: br.duration_seconds != null ? fmtDuration(br.duration_seconds) : "—",
        progress: 100,
        violations: br.violations?.total ?? 0,
        createdBy: br.created_by ?? undefined,
      };

      runsArray.push(run);
      existingIds.add(br.run_id);
    }

    // Newest first: real runs (with a date startedAt) before seeded ones.
    runsArray.sort((a, b) => {
      if (a.startedAt === "—" && b.startedAt !== "—") return 1;
      if (a.startedAt !== "—" && b.startedAt === "—") return -1;
      return b.startedAt.localeCompare(a.startedAt);
    });

    emit();
  } catch (err) {
    console.warn("seedRunsFromBackend:", err);
  }
}

function fmtStartedAt(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fmtDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m < 60) return s > 0 ? `${m}m ${s}s` : `${m}m`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  return rem > 0 ? `${h}h ${rem}m` : `${h}h`;
}

let nextRunCounter = 1100;
function nextRunId() {
  nextRunCounter += 1;
  return `run-${nextRunCounter}`;
}

function fmtTime(d: Date) {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

export interface CreateRunInput {
  scenarioId: string;
  scenarioName?: string;
  networkName?: string;
  /** The actual network id — passed through so results can fetch CSVs. */
  networkId?: string;
  /** Backend-supplied id, when available — otherwise we generate one. */
  runId?: string;
  /** Initial status; defaults to "completed" for backend-confirmed runs. */
  status?: Run["status"];
  /** ISO datetime string from the backend response — formatted by createRun. */
  startedAtIso?: string;
  /** Raw seconds from the backend response — formatted by createRun. */
  durationSeconds?: number;
  /** Total violation count from the backend response. */
  violations?: number;
  /** Name of the user who triggered the run — persisted so it survives refresh. */
  createdBy?: string;
}

/**
 * Patch an existing run's mutable fields (status, progress).
 * No-op if the run id is not found.
 */
export function updateRun(
  id: string,
  patch: Partial<Pick<Run, "status" | "progress">>,
): void {
  const idx = runsArray.findIndex((r) => r.id === id);
  if (idx === -1) return;
  Object.assign(runsArray[idx], patch);
  emit();
}

/**
 * Append a run to the in-memory store after a simulation completes.
 * If a run with the same id already exists (e.g. seeded from backend),
 * update it in place so the UI reflects the latest startedAt time.
 */
export function removeRun(id: string): void {
  const idx = runsArray.findIndex((r) => r.id === id);
  if (idx !== -1) {
    runsArray.splice(idx, 1);
    emit();
  }
}

/**
 * Delete a run from the backend (DB + result files) and remove it from
 * the in-memory store. Throws on network/API error.
 *
 * Also removes the associated scenario so the Scenarios KPI card and the
 * Violations Overview stay in sync.  Backend-seeded runs land with
 * scenarioId="" after a page refresh, so we fall back to matching by name +
 * networkId to still find and remove the parent scenario.
 */
export async function deleteRun(id: string): Promise<void> {
  const run = runsArray.find((r) => r.id === id) as (Run & { networkId?: string }) | undefined;
  const networkId = run?.networkId ?? "";

  // Resolve scenarioId — prefer the stored field, fall back to name-match
  // for runs that were re-seeded from the backend (where scenarioId is "").
  let scenarioId = run?.scenarioId ?? "";
  if (!scenarioId && run) {
    const match = getAllScenarios().find(
      (s) => s.name === run.scenarioName && s.networkId === networkId,
    );
    if (match) scenarioId = match.id;
  }

  await deleteRunApi(id, networkId);
  removeRun(id);

  if (scenarioId) {
    await removeScenario(scenarioId).catch(() => {});
  }
}

export function createRun(input: CreateRunInput): string {
  const scn = getAllScenarios().find((s) => s.id === input.scenarioId);
  const net = scn ? networks.find((n) => n.id === scn.networkId) : undefined;
  const id = input.runId ?? nextRunId();

  const newRun: Run & { networkId?: string; createdBy?: string } = {
    id,
    scenarioId: input.scenarioId,
    scenarioName: input.scenarioName ?? scn?.name ?? "Custom scenario",
    networkName: input.networkName ?? net?.name ?? "Unknown network",
    networkId: input.networkId,
    status: input.status ?? "completed",
    startedAt: input.startedAtIso ? fmtStartedAt(input.startedAtIso) : fmtTime(new Date()),
    duration: input.durationSeconds != null ? fmtDuration(input.durationSeconds) : "—",
    progress: input.status === "completed" || !input.status ? 100 : 0,
    violations: input.violations ?? 0,
    createdBy: input.createdBy,
  };

  // If already seeded from backend, replace it so startedAt is updated.
  const existingIdx = runsArray.findIndex((r) => r.id === id);
  if (existingIdx !== -1) {
    runsArray.splice(existingIdx, 1);
  }
  runsArray.unshift(newRun);
  emit();
  return id;
}
