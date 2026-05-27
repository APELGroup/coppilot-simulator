import { API_BASE, apiFetch } from "@/lib/api";
import {
  daysInMonth,
  pad2,
  type StoredSimulationResult,
  type SimHorizon,
} from "@/lib/run-context";

export type ResultKind = "vm-pu" | "line-loading" | "trafo-loading";

export interface ParsedCsv {
  /** Column headers (excluding the first index column if present). */
  columns: string[];
  /** rows[t][c] — numeric value at time step t for column c. */
  rows: number[][];
  /** Optional time index from the CSV (string), if present in first column. */
  index: string[];
}

/**
 * Parse a pandas-style CSV. Auto-detects "," vs ";" separator and treats an
 * empty / "Unnamed" first header cell as a row index column (stripped from
 * data columns).
 */
export function parseCsv(text: string): ParsedCsv {
  const lines = text
    .split(/\r?\n/)
    .filter((l) => l.trim().length > 0);
  if (lines.length === 0) {
    return { columns: [], rows: [], index: [] };
  }

  // Auto-detect separator from the first line: prefer the one that produces
  // more fields. Defaults to ",".
  const first = lines[0];
  const sep = first.split(";").length > first.split(",").length ? ";" : ",";
  const split = (line: string) => line.split(sep).map((c) => c.trim());

  const header = split(lines[0]);
  const firstHeader = header[0] ?? "";
  const lc = firstHeader.toLowerCase();
  const hasIndex =
    firstHeader === "" ||
    lc.startsWith("unnamed") ||
    lc === "time" ||
    lc === "timestamp" ||
    lc === "index" ||
    lc === "step";
  const columns = (hasIndex ? header.slice(1) : header).map((h) => h.trim());

  const rows: number[][] = [];
  const index: string[] = [];
  for (let i = 1; i < lines.length; i++) {
    const cells = split(lines[i]);
    if (hasIndex) index.push(cells[0]);
    const data = (hasIndex ? cells.slice(1) : cells).map((v) => {
      if (v === "" || v === undefined) return NaN;
      const n = Number(v);
      return Number.isFinite(n) ? n : NaN;
    });
    rows.push(data);
  }
  return { columns, rows, index };
}

export async function fetchResultCsv(
  networkId: string,
  runId: string,
  kind: ResultKind,
): Promise<ParsedCsv> {
  const url = `${API_BASE}/networks/${networkId}/results/${runId}/${kind}`;
  const res = await apiFetch(url);
  if (!res.ok) {
    throw new Error(`Failed to load ${kind} (${res.status})`);
  }
  const text = await res.text();
  return parseCsv(text);
}

/** Compute per-row min / mean / max across all columns. */
export function envelope(parsed: ParsedCsv): { min: number; mean: number; max: number }[] {
  return parsed.rows.map((row) => {
    let min = Infinity;
    let max = -Infinity;
    let sum = 0;
    let n = 0;
    for (const v of row) {
      if (!Number.isFinite(v)) continue;
      if (v < min) min = v;
      if (v > max) max = v;
      sum += v;
      n++;
    }
    if (n === 0) return { min: NaN, mean: NaN, max: NaN };
    return { min, mean: sum / n, max };
  });
}

/** Generate ISO timestamps for each step given the run context.
 *  @param stepMinutes - interval between steps in minutes (default 15; use 30 for OpenDSS networks)
 */
export function generateTimestamps(
  ctx: Pick<StoredSimulationResult, "horizon" | "year" | "month" | "day">,
  steps: number,
  stepMinutes = 15,
): Date[] {
  const startDay =
    ctx.horizon === "month" ? 1 : ctx.day ?? 1;
  const start = new Date(Date.UTC(ctx.year, ctx.month - 1, startDay, 0, 0, 0));
  const out: Date[] = [];
  for (let i = 0; i < steps; i++) {
    out.push(new Date(start.getTime() + i * stepMinutes * 60 * 1000));
  }
  return out;
}

export function expectedStepCount(
  ctx: Pick<StoredSimulationResult, "horizon" | "year" | "month">,
): number {
  if (ctx.horizon === "day") return 96;
  if (ctx.horizon === "week") return 7 * 96;
  return daysInMonth(ctx.year, ctx.month) * 96;
}

/** Format a Date for the X axis tick depending on horizon. */
export function formatAxisTick(d: Date, horizon: SimHorizon): string {
  const hh = pad2(d.getUTCHours());
  const mm = pad2(d.getUTCMinutes());
  const DD = pad2(d.getUTCDate());
  const MM = pad2(d.getUTCMonth() + 1);
  if (horizon === "day") return `${hh}:${mm}`;
  if (horizon === "week") return `${DD}/${MM} ${hh}:${mm}`;
  return `${DD}/${MM} ${hh}:${mm}`;
}

/** Full timestamp shown in tooltips. */
export function formatFullTimestamp(d: Date): string {
  const yyyy = d.getUTCFullYear();
  const MM = pad2(d.getUTCMonth() + 1);
  const DD = pad2(d.getUTCDate());
  const hh = pad2(d.getUTCHours());
  const mm = pad2(d.getUTCMinutes());
  return `${yyyy}-${MM}-${DD} ${hh}:${mm}`;
}
