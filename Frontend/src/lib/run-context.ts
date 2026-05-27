export type SimHorizon = "day" | "week" | "month";

export interface StoredSimulationResult {
  networkId: string;
  networkName?: string;
  runId: string;
  urls: Record<string, string>;
  horizon: SimHorizon;
  mode: "balanced" | "unbalanced";
  year: number;
  month: number;
  day: number | null;
  raw?: unknown;
  at: string;
}

export function readLastSimulationResult(): StoredSimulationResult | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem("lastSimulationResult");
    if (!raw) return null;
    return JSON.parse(raw) as StoredSimulationResult;
  } catch {
    return null;
  }
}

const ALL_RESULTS_KEY = "allSimulationResults";

/** Persist a result keyed by runId so it can be retrieved later. */
export function saveSimulationResult(result: StoredSimulationResult): void {
  if (typeof window === "undefined") return;
  try {
    const raw = sessionStorage.getItem(ALL_RESULTS_KEY);
    const all: Record<string, StoredSimulationResult> = raw
      ? (JSON.parse(raw) as Record<string, StoredSimulationResult>)
      : {};
    all[result.runId] = result;
    sessionStorage.setItem(ALL_RESULTS_KEY, JSON.stringify(all));
    // Also keep the "last" pointer for backward compat
    sessionStorage.setItem("lastSimulationResult", JSON.stringify(result));
  } catch {
    // quota exceeded or SSR — silently ignore
  }
}

/** Look up a previously saved result by runId. Returns null if not found. */
export function readSimulationResult(
  runId: string,
): StoredSimulationResult | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(ALL_RESULTS_KEY);
    if (!raw) return null;
    const all = JSON.parse(raw) as Record<string, StoredSimulationResult>;
    return all[runId] ?? null;
  } catch {
    return null;
  }
}

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

export function monthName(month: number) {
  return MONTH_NAMES[(month - 1 + 12) % 12] ?? String(month);
}

export function daysInMonth(year: number, month: number) {
  return new Date(year, month, 0).getDate();
}

export function pad2(n: number) {
  return String(n).padStart(2, "0");
}

export function timeStepCount(ctx: Pick<StoredSimulationResult, "horizon" | "year" | "month">) {
  if (ctx.horizon === "day") return 96;
  if (ctx.horizon === "week") return 7 * 96;
  return daysInMonth(ctx.year, ctx.month) * 96;
}

export function timeWindowLabel(ctx: StoredSimulationResult) {
  const { horizon, year, month, day } = ctx;
  if (horizon === "day" && day) {
    const lastTime = ctx.networkId.startsWith("opendss-") ? "23:30" : "23:45";
    return `${year}-${pad2(month)}-${pad2(day)} · 00:00–${lastTime}`;
  }
  if (horizon === "week" && day) {
    const start = new Date(Date.UTC(year, month - 1, day));
    const end = new Date(start);
    end.setUTCDate(end.getUTCDate() + 6);
    const fmt = (d: Date) =>
      `${d.getUTCFullYear()}-${pad2(d.getUTCMonth() + 1)}-${pad2(d.getUTCDate())}`;
    return `${fmt(start)} → ${fmt(end)}`;
  }
  return `${monthName(month)} ${year} (full month)`;
}

/**
 * Convert a 0-based 15-minute time step index to a label depending on the
 * horizon. Returns "HH:mm" for day runs, "YYYY-MM-DD HH:mm" for week/month.
 */
export function formatTimeStep(
  step: number,
  ctx: Pick<StoredSimulationResult, "horizon" | "year" | "month" | "day">,
): string {
  const minutes = step * 15;
  const hh = Math.floor(minutes / 60) % 24;
  const mm = minutes % 60;
  const hhmm = `${pad2(hh)}:${pad2(mm)}`;

  if (ctx.horizon === "day") {
    return hhmm;
  }

  const startDay =
    ctx.horizon === "week" && ctx.day ? ctx.day : 1;
  const dayOffset = Math.floor(minutes / (60 * 24));
  const date = new Date(Date.UTC(ctx.year, ctx.month - 1, startDay + dayOffset));
  return `${date.getUTCFullYear()}-${pad2(date.getUTCMonth() + 1)}-${pad2(date.getUTCDate())} ${hhmm}`;
}

/**
 * Parse a backend runId string into its constituent parts.
 * Formats produced by main.py:
 *   day:     "2016-01-05_{timestamp}"
 *   week:    "2016-01-05_week_{timestamp}"
 *   month:   "2016-01_{timestamp}"
 *   opendss: "day{NNN}_{YYYYMMDD}-{HHMMSS}"
 *
 * Returns null if the string doesn't match any known pattern.
 */
export function parseRunId(
  runId: string,
): Pick<StoredSimulationResult, "horizon" | "year" | "month" | "day"> | null {
  // OpenDSS: day{NNN}_{YYYYMMDD}-{HHMMSS} e.g. "day015_20260506-103311"
  const openDssMatch = runId.match(/^day(\d{1,3})_(\d{4})(\d{2})(\d{2})-\d{6}/);
  if (openDssMatch) {
    const dayOfYear = parseInt(openDssMatch[1], 10);
    const year = parseInt(openDssMatch[2], 10);
    // Convert day-of-year to calendar month + day
    const d = new Date(Date.UTC(year, 0, dayOfYear));
    return {
      horizon: "day",
      year,
      month: d.getUTCMonth() + 1,
      day: d.getUTCDate(),
    };
  }
  // Week: YYYY-MM-DD_week_{timestamp} or legacy YYYY-MM-DD_week
  const weekMatch = runId.match(/^(\d{4})-(\d{2})-(\d{2})_week/);
  if (weekMatch) {
    return {
      horizon: "week",
      year: parseInt(weekMatch[1], 10),
      month: parseInt(weekMatch[2], 10),
      day: parseInt(weekMatch[3], 10),
    };
  }
  // Day: YYYY-MM-DD_{timestamp} or legacy YYYY-MM-DD
  const dayMatch = runId.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (dayMatch) {
    return {
      horizon: "day",
      year: parseInt(dayMatch[1], 10),
      month: parseInt(dayMatch[2], 10),
      day: parseInt(dayMatch[3], 10),
    };
  }
  // Month: YYYY-MM_{timestamp} or legacy YYYY-MM
  const monthMatch = runId.match(/^(\d{4})-(\d{2})/);
  if (monthMatch) {
    return {
      horizon: "month",
      year: parseInt(monthMatch[1], 10),
      month: parseInt(monthMatch[2], 10),
      day: null,
    };
  }
  return null;
}

/**
 * Build a StoredSimulationResult from the information available in the
 * runs-store (networkId, networkName, runId). Falls back to sessionStorage
 * for the full context if the runId can't be parsed (legacy / mock runs).
 */
export function buildRunContext(
  networkId: string,
  runId: string,
  networkName?: string,
): StoredSimulationResult | null {
  const parsed = parseRunId(runId);
  if (!parsed) {
    // Not a real backend runId — try sessionStorage as fallback
    return readSimulationResult(runId) ?? readLastSimulationResult();
  }
  const mode: "balanced" | "unbalanced" =
    networkId.includes("unbalanced") ? "unbalanced" : "balanced";
  return {
    networkId,
    networkName,
    runId,
    urls: {
      "vm-pu": `/networks/${networkId}/results/${runId}/vm-pu`,
      "line-loading": `/networks/${networkId}/results/${runId}/line-loading`,
      "trafo-loading": `/networks/${networkId}/results/${runId}/trafo-loading`,
    },
    mode,
    at: new Date().toISOString(),
    ...parsed,
  };
}