import { useEffect, useMemo, useState } from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SeverityBadge } from "@/components/app-shell";
import type { ViolationCategory, Severity } from "@/lib/mock-data";
import type { StoredSimulationResult } from "@/lib/run-context";
import {
  fetchResultCsv,
  generateTimestamps,
  formatAxisTick,
  type ParsedCsv,
  type ResultKind,
} from "@/lib/results-data";
import {
  fetchResultPhasesColumnSummary,
  type PhaseColumnSummary,
} from "@/lib/api";
import {
  ArrowDown,
  ArrowUp,
  Cable,
  Zap,
  Search,
  Loader2,
  ShieldAlert,
} from "lucide-react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Cell,
} from "recharts";

const catMeta: Record<
  ViolationCategory,
  { label: string; icon: typeof Cable; tone: string }
> = {
  under_voltage: { label: "Under-voltage", icon: ArrowDown, tone: "text-destructive" },
  over_voltage: { label: "Over-voltage", icon: ArrowUp, tone: "text-warning-foreground" },
  line_overload: { label: "Line overload", icon: Cable, tone: "text-info" },
  transformer_overload: { label: "Trafo overload", icon: Zap, tone: "text-primary" },
};

interface RealViolation {
  id: string;
  category: ViolationCategory;
  asset: string;
  worstValue: number;
  limit: number;
  severity: Severity;
  worstStep: number;
  time: string;
  runId: string;
}

function voltageSeverity(v: number): Severity {
  // deviation from nearest limit (0.94 lower / 1.06 upper)
  const dev = v < 0.94 ? 0.94 - v : v - 1.06;
  if (dev >= 0.05) return "critical";
  if (dev >= 0.03) return "high";
  if (dev >= 0.01) return "medium";
  return "low";
}

function loadingSeverity(p: number): Severity {
  if (p > 130) return "critical";
  if (p > 115) return "high";
  if (p > 105) return "medium";
  return "low";
}

function computeVoltageViolations(
  csv: ParsedCsv,
  ts: Date[],
  runId: string,
  horizon: StoredSimulationResult["horizon"],
  minStepOverride: number[] | null = null,
  maxStepOverride: number[] | null = null,
): { under: RealViolation[]; over: RealViolation[] } {
  const under: RealViolation[] = [];
  const over: RealViolation[] = [];
  const cols = csv.columns.length;
  for (let c = 0; c < cols; c++) {
    let minV = Infinity;
    let minStep = -1;
    let maxV = -Infinity;
    let maxStep = -1;
    for (let r = 0; r < csv.rows.length; r++) {
      const v = csv.rows[r]?.[c];
      if (typeof v !== "number" || !Number.isFinite(v)) continue;
      if (v < minV) { minV = v; minStep = r; }
      if (v > maxV) { maxV = v; maxStep = r; }
    }
    // For unbalanced networks the ParsedCsv has only 2 synthetic rows; the real
    // timestep comes from the step-override arrays returned by column-summary.
    const effectiveMinStep = minStepOverride?.[c] ?? minStep;
    const effectiveMaxStep = maxStepOverride?.[c] ?? maxStep;
    const asset = csv.columns[c];
    if (minStep >= 0 && minV < 0.94) {
      under.push({
        id: `uv-${asset}`,
        category: "under_voltage",
        asset: `Bus ${asset}`,
        worstValue: minV,
        limit: 0.94,
        severity: voltageSeverity(minV),
        worstStep: effectiveMinStep,
        time: ts[effectiveMinStep] ? formatAxisTick(ts[effectiveMinStep], horizon) : "—",
        runId,
      });
    }
    if (maxStep >= 0 && maxV > 1.06) {
      over.push({
        id: `ov-${asset}`,
        category: "over_voltage",
        asset: `Bus ${asset}`,
        worstValue: maxV,
        limit: 1.06,
        severity: voltageSeverity(maxV),
        worstStep: effectiveMaxStep,
        time: ts[effectiveMaxStep] ? formatAxisTick(ts[effectiveMaxStep], horizon) : "—",
        runId,
      });
    }
  }
  return { under, over };
}

function computeLoadingViolations(
  csv: ParsedCsv,
  ts: Date[],
  runId: string,
  horizon: StoredSimulationResult["horizon"],
  category: "line_overload" | "transformer_overload",
  prefix: string,
  maxStepOverride: number[] | null = null,
): RealViolation[] {
  const out: RealViolation[] = [];
  const cols = csv.columns.length;
  for (let c = 0; c < cols; c++) {
    let maxV = -Infinity;
    let maxStep = -1;
    for (let r = 0; r < csv.rows.length; r++) {
      const v = csv.rows[r]?.[c];
      if (typeof v !== "number" || !Number.isFinite(v)) continue;
      if (v > maxV) { maxV = v; maxStep = r; }
    }
    const effectiveMaxStep = maxStepOverride?.[c] ?? maxStep;
    if (maxStep >= 0 && maxV > 100) {
      const asset = csv.columns[c];
      out.push({
        id: `${category}-${asset}`,
        category,
        asset: `${prefix} ${asset}`,
        worstValue: maxV,
        limit: 100,
        severity: loadingSeverity(maxV),
        worstStep: effectiveMaxStep,
        time: ts[effectiveMaxStep] ? formatAxisTick(ts[effectiveMaxStep], horizon) : "—",
        runId,
      });
    }
  }
  return out;
}

interface FetchState {
  loading: boolean;
  vm: ParsedCsv | null;
  ll: ParsedCsv | null;
  tl: ParsedCsv | null;
  // Per-element timestep indices for the worst value (unbalanced only; null = balanced)
  vmMinStep: number[] | null;
  vmMaxStep: number[] | null;
  llMaxStep: number[] | null;
  tlMaxStep: number[] | null;
  /** Actual number of timesteps in the run (for building the ts[] array). */
  nRows: number;
  errors: Partial<Record<ResultKind, string>>;
}

/**
 * Convert a PhaseColumnSummary (per-element min/max across all timesteps and
 * all phases) into a 2-row ParsedCsv so the existing violation-compute
 * functions work unchanged.
 *
 * Row 0 = worst-case minimum per element (for under-voltage / threshold checks)
 * Row 1 = worst-case maximum per element (for over-voltage / overload checks)
 */
function columnSummaryToParsedCsv(summary: PhaseColumnSummary): ParsedCsv {
  return { columns: summary.columns, rows: [summary.min, summary.max], index: ["min", "max"] };
}

const _EMPTY_FETCH: FetchState = {
  loading: false,
  vm: null, ll: null, tl: null,
  vmMinStep: null, vmMaxStep: null, llMaxStep: null, tlMaxStep: null,
  nRows: 0,
  errors: {},
};

function useAllCsvs(networkId?: string, runId?: string, mode?: string): FetchState {
  const isUnbalanced = mode === "unbalanced";
  const [state, setState] = useState<FetchState>({
    ..._EMPTY_FETCH,
    loading: !!(networkId && runId),
  });

  useEffect(() => {
    if (!networkId || !runId) {
      setState(_EMPTY_FETCH);
      return;
    }
    let cancelled = false;
    setState({ ..._EMPTY_FETCH, loading: true });

    type LoadResult = {
      kind: ResultKind;
      data: ParsedCsv | null;
      summary: PhaseColumnSummary | null;
      error: string | null;
    };

    const load = async (kind: ResultKind): Promise<LoadResult> => {
      try {
        if (isUnbalanced) {
          const summary = await fetchResultPhasesColumnSummary(networkId, runId, kind);
          return { kind, data: columnSummaryToParsedCsv(summary), summary, error: null };
        } else {
          const data = await fetchResultCsv(networkId, runId, kind);
          return { kind, data, summary: null, error: null };
        }
      } catch (e) {
        return { kind, data: null, summary: null, error: (e as Error).message };
      }
    };

    Promise.all([load("vm-pu"), load("line-loading"), load("trafo-loading")]).then(
      (results) => {
        if (cancelled) return;
        const errors: Partial<Record<ResultKind, string>> = {};
        let vm: ParsedCsv | null = null;
        let ll: ParsedCsv | null = null;
        let tl: ParsedCsv | null = null;
        let vmMinStep: number[] | null = null;
        let vmMaxStep: number[] | null = null;
        let llMaxStep: number[] | null = null;
        let tlMaxStep: number[] | null = null;
        let nRows = 0;
        for (const r of results) {
          if (r.error) errors[r.kind] = r.error;
          if (r.kind === "vm-pu") {
            vm = r.data;
            vmMinStep = r.summary?.min_step ?? null;
            vmMaxStep = r.summary?.max_step ?? null;
            if (r.summary?.n_rows) nRows = r.summary.n_rows;
          }
          if (r.kind === "line-loading") {
            ll = r.data;
            llMaxStep = r.summary?.max_step ?? null;
            if (r.summary?.n_rows && !nRows) nRows = r.summary.n_rows;
          }
          if (r.kind === "trafo-loading") {
            tl = r.data;
            tlMaxStep = r.summary?.max_step ?? null;
          }
        }
        setState({ loading: false, vm, ll, tl, vmMinStep, vmMaxStep, llMaxStep, tlMaxStep, nRows, errors });
      },
    );
    return () => { cancelled = true; };
  }, [networkId, runId, isUnbalanced]);

  return state;
}

export function ViolationDetectionSection({
  runId,
  runContext,
}: {
  runId?: string;
  networkName?: string;
  runContext?: StoredSimulationResult;
  autoRun?: boolean;
}) {
  const networkId = runContext?.networkId;
  const effectiveRunId = runContext?.runId ?? runId ?? "";
  const fetchState = useAllCsvs(networkId, runContext?.runId, runContext?.mode);

  const violations = useMemo<RealViolation[]>(() => {
    if (!runContext) return [];
    const { vm, ll, tl, vmMinStep, vmMaxStep, llMaxStep, tlMaxStep, nRows } = fetchState;
    const list: RealViolation[] = [];
    const horizon = runContext.horizon;
    // For unbalanced networks the ParsedCsv has only 2 synthetic rows, but we
    // need ts[] to cover all real timesteps so step overrides can index into it.
    const stepsForTs = nRows > 0
      ? nRows
      : Math.max(vm?.rows.length ?? 0, ll?.rows.length ?? 0, tl?.rows.length ?? 0);
    if (stepsForTs === 0) return [];
    const stepMinutes = runContext.networkId.startsWith("opendss-") ? 30 : 15;
    const ts = generateTimestamps(runContext, stepsForTs, stepMinutes);
    if (vm) {
      const { under, over } = computeVoltageViolations(
        vm, ts, effectiveRunId, horizon, vmMinStep, vmMaxStep,
      );
      list.push(...under, ...over);
    }
    if (ll) {
      list.push(
        ...computeLoadingViolations(ll, ts, effectiveRunId, horizon, "line_overload", "Line", llMaxStep),
      );
    }
    if (tl) {
      list.push(
        ...computeLoadingViolations(tl, ts, effectiveRunId, horizon, "transformer_overload", "Trafo", tlMaxStep),
      );
    }
    return list;
  }, [runContext, fetchState, effectiveRunId]);

  const [q, setQ] = useState("");
  const [cat, setCat] = useState<string>("all");
  const [sev, setSev] = useState<string>("all");

  const sevColors: Record<string, string> = {
    low: "oklch(0.65 0.14 230)",
    medium: "oklch(0.75 0.16 75)",
    high: "oklch(0.58 0.22 25)",
    critical: "oklch(0.45 0.22 25)",
  };

  const filtered = violations.filter(
    (v) =>
      (cat === "all" || v.category === cat) &&
      (sev === "all" || v.severity === sev) &&
      (q === "" || v.asset.toLowerCase().includes(q.toLowerCase())),
  );

  const byCategory = (Object.keys(catMeta) as ViolationCategory[]).map((c) => ({
    s: catMeta[c].label,
    category: c,
    n: violations.filter((v) => v.category === c).length,
  }));

  const categoryColors: Record<ViolationCategory, string> = {
    under_voltage: "oklch(0.58 0.22 25)",
    over_voltage: "oklch(0.75 0.16 75)",
    line_overload: "oklch(0.65 0.14 230)",
    transformer_overload: "oklch(0.55 0.18 290)",
  };

  const fmtValue = (v: RealViolation) =>
    v.category === "under_voltage" || v.category === "over_voltage"
      ? `${v.worstValue.toFixed(4)} pu`
      : `${v.worstValue.toFixed(1)}%`;
  const fmtLimit = (v: RealViolation) =>
    v.category === "under_voltage" || v.category === "over_voltage"
      ? `${v.limit.toFixed(2)} pu`
      : `${v.limit.toFixed(0)}%`;

  if (!runContext) {
    return (
      <section className="mt-8">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold tracking-tight flex items-center gap-2">
              <ShieldAlert className="h-4 w-4 text-primary" />
              Violation Detection Results
            </h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              Run a backend simulation to detect violations.
            </p>
          </div>
        </div>
        <Card className="p-6 text-sm text-muted-foreground border-dashed">
          No backend simulation result available. Run a simulation from the
          Scenario Builder to view violations.
        </Card>
      </section>
    );
  }

  return (
    <section className="mt-8">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold tracking-tight flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 text-primary" />
            Violation Detection Results
          </h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Computed from backend CSV results for run {effectiveRunId}.
          </p>
        </div>
      </div>

      {fetchState.loading && (
        <Card className="p-6 mb-6">
          <div className="flex items-center gap-3 mb-4">
            <Loader2 className="h-5 w-5 text-primary animate-spin" />
            <div>
              <div className="text-sm font-semibold">Loading CSV results…</div>
              <div className="text-xs text-muted-foreground">
                Fetching vm_pu, line and trafo loading
              </div>
            </div>
          </div>
          <Progress value={50} />
        </Card>
      )}

      {!fetchState.loading && (
        <>
          <div className="grid gap-4 grid-cols-2 lg:grid-cols-4 mb-6">
            {(Object.keys(catMeta) as ViolationCategory[]).map((c) => {
              const meta = catMeta[c];
              const Icon = meta.icon;
              const n = violations.filter((v) => v.category === c).length;
              return (
                <Card key={c} className="p-5">
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="text-xs uppercase tracking-wider text-muted-foreground font-medium">
                        {meta.label}
                      </div>
                      <div className="mt-2 text-3xl font-semibold">{n}</div>
                    </div>
                    <div className={"rounded-md bg-muted p-2 " + meta.tone}>
                      <Icon className="h-4 w-4" />
                    </div>
                  </div>
                </Card>
              );
            })}
          </div>

          {violations.length === 0 ? (
            <Card className="p-6 text-sm text-muted-foreground border-dashed">
              No violations detected for this run.
            </Card>
          ) : (
            <>
              <Card className="p-5 mb-6">
                <div className="text-sm font-semibold mb-1">
                  Violations by category
                </div>
                <div className="text-xs text-muted-foreground mb-4">
                  Count of violating assets by violation type
                </div>
                <div className="h-56">
                  <ResponsiveContainer>
                    <BarChart
                      data={byCategory}
                      margin={{ top: 5, right: 10, left: -10, bottom: 0 }}
                    >
                      <CartesianGrid
                        strokeDasharray="3 3"
                        stroke="oklch(0.91 0.01 240)"
                      />
                      <XAxis
                        dataKey="s"
                        stroke="oklch(0.5 0.02 250)"
                        fontSize={11}
                      />
                      <YAxis
                        stroke="oklch(0.5 0.02 250)"
                        fontSize={11}
                        allowDecimals={false}
                      />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: "var(--card)",
                          border: "1px solid var(--border)",
                          borderRadius: 6,
                          fontSize: 12,
                        }}
                      />
                      <Bar dataKey="n" radius={[4, 4, 0, 0]}>
                        {byCategory.map((d) => (
                          <Cell key={d.category} fill={categoryColors[d.category]} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </Card>

              <Card className="p-4 mb-6">
                <div className="flex flex-col md:flex-row gap-3">
                  <div className="relative flex-1">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      placeholder="Search asset…"
                      value={q}
                      onChange={(e) => setQ(e.target.value)}
                      className="pl-9"
                    />
                  </div>
                  <Select value={cat} onValueChange={setCat}>
                    <SelectTrigger className="w-full md:w-52">
                      <SelectValue placeholder="Category" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All categories</SelectItem>
                      <SelectItem value="under_voltage">Under-voltage</SelectItem>
                      <SelectItem value="over_voltage">Over-voltage</SelectItem>
                      <SelectItem value="line_overload">Line overload</SelectItem>
                      <SelectItem value="transformer_overload">
                        Transformer overload
                      </SelectItem>
                    </SelectContent>
                  </Select>
                  <Select value={sev} onValueChange={setSev}>
                    <SelectTrigger className="w-full md:w-44">
                      <SelectValue placeholder="Severity" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All severities</SelectItem>
                      <SelectItem value="low">Low</SelectItem>
                      <SelectItem value="medium">Medium</SelectItem>
                      <SelectItem value="high">High</SelectItem>
                      <SelectItem value="critical">Critical</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </Card>

              <Card className="overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/40">
                      <tr className="text-left text-xs uppercase tracking-wider text-muted-foreground">
                        <th className="py-3 px-4 font-medium">Category</th>
                        <th className="py-3 px-4 font-medium">Asset</th>
                        <th className="py-3 px-4 font-medium">Worst value</th>
                        <th className="py-3 px-4 font-medium">Limit</th>
                        <th className="py-3 px-4 font-medium">Severity</th>
                        <th className="py-3 px-4 font-medium">Time</th>
                        <th className="py-3 px-4 font-medium">Run</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filtered.map((v) => {
                        const Icon = catMeta[v.category].icon;
                        return (
                          <tr
                            key={v.id}
                            className="border-t border-border hover:bg-muted/30"
                          >
                            <td className="py-3 px-4">
                              <span className="inline-flex items-center gap-2">
                                <Icon
                                  className={
                                    "h-3.5 w-3.5 " + catMeta[v.category].tone
                                  }
                                />
                                {catMeta[v.category].label}
                              </span>
                            </td>
                            <td className="py-3 px-4 font-mono text-xs">
                              {v.asset}
                            </td>
                            <td className="py-3 px-4 font-mono text-xs font-medium">
                              {fmtValue(v)}
                            </td>
                            <td className="py-3 px-4 font-mono text-xs text-muted-foreground">
                              {fmtLimit(v)}
                            </td>
                            <td className="py-3 px-4">
                              <SeverityBadge severity={v.severity} />
                            </td>
                            <td className="py-3 px-4 text-muted-foreground">
                              {v.time}
                            </td>
                            <td className="py-3 px-4 font-mono text-xs">
                              {v.runId}
                            </td>
                          </tr>
                        );
                      })}
                      {filtered.length === 0 && (
                        <tr>
                          <td
                            colSpan={7}
                            className="text-center py-12 text-muted-foreground text-sm"
                          >
                            No violations match your filters.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </Card>
            </>
          )}
        </>
      )}
    </section>
  );
}
