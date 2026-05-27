import { createFileRoute } from "@tanstack/react-router";
import { AppShell, PageHeader } from "@/components/app-shell";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useEffect, useMemo, useRef, useState } from "react";
import { getAllScenarios } from "@/lib/scenarios-store";
import { useNetworks } from "@/lib/networks-store";
import { useRuns } from "@/lib/runs-store";
import { API_BASE, apiFetch, fetchResultEnvelope, fetchResultColumn, fetchResultPhases, fetchResultPhasesColumn, fetchPfViolations, type EnvelopeResult, type PhasesResult, type PowerFlowViolations } from "@/lib/api";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
  Legend,
} from "recharts";
import {
  TrendingDown,
  TrendingUp,
  Cable,
  Zap,
  Play,
  Loader2,
  BarChart3,
  RotateCcw,
  Microscope,
  Check,
  ChevronsUpDown,
  AlertTriangle,
  CheckCircle2,
} from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { cn } from "@/lib/utils";
import { ViolationDetectionSection } from "@/components/violation-detection-section";
import {
  readLastSimulationResult,
  readSimulationResult,
  buildRunContext,
  monthName,
  timeWindowLabel,
  timeStepCount,
  type StoredSimulationResult,
} from "@/lib/run-context";
import {
  generateTimestamps,
  formatAxisTick,
  formatFullTimestamp,
  type ResultKind,
} from "@/lib/results-data";

export const Route = createFileRoute("/results")({
  validateSearch: (search: Record<string, unknown>): { runId?: string; networkId?: string } => ({
    runId: typeof search.runId === "string" ? search.runId : undefined,
    networkId: typeof search.networkId === "string" ? search.networkId : undefined,
  }),
  head: () => ({
    meta: [
      { title: "Results & Analytics — DT Lab" },
      {
        name: "description",
        content: "Interactively load and analyze simulation results.",
      },
    ],
  }),
  component: Results,
});

type LoadState = "idle" | "loading" | "ready";

function Results() {
  const networks = useNetworks();
  const runs = useRuns();
  const { runId: incomingRunId, networkId: incomingNetworkId } = Route.useSearch();
  const incomingRun = incomingRunId
    ? runs.find((r) => r.id === incomingRunId && r.status === "completed")
    : undefined;
  const incomingScenario = incomingRun
    ? getAllScenarios().find((s) => s.id === incomingRun.scenarioId)
    : undefined;

  const [networkId, setNetworkId] = useState<string>(
    incomingScenario?.networkId ??
    (incomingRun as (typeof incomingRun) & { networkId?: string })?.networkId ??
    incomingNetworkId ??
    "",
  );
  const [runId, setRunId] = useState<string>(incomingRun?.id ?? incomingRunId ?? "");

  const hasDirectLink = !incomingRun && !!incomingRunId && !!incomingNetworkId;
  const [state, setState] = useState<LoadState>(
    incomingRun || hasDirectLink ? "ready" : "idle",
  );
  const [progress, setProgress] = useState(incomingRun || hasDirectLink ? 100 : 0);
  const autoLoadedRef = useRef<string | undefined>(incomingRun?.id ?? (hasDirectLink ? incomingRunId : undefined));

  const completed = runs.filter((r) => r.status === "completed");
  const networkRuns = completed.filter((r) => {
    if (!networkId) return true;
    const scn = getAllScenarios().find((s) => s.id === r.scenarioId);
    const rNetworkId = scn?.networkId ?? (r as typeof r & { networkId?: string }).networkId;
    return rNetworkId === networkId;
  });

  const selectedNetwork = networks.find((n) => n.id === networkId);
  const selectedRun = runs.find((r) => r.id === runId);

  // Derive runContext directly from the selected networkId + runId.
  // buildRunContext parses the runId string (e.g. "2016-01-01_week") to
  // extract horizon/year/month/day — no sessionStorage dependency needed.
  // After a restart, the run may carry its own networkId from localStorage.
  const resolvedNetworkId =
    networkId ||
    (selectedRun as (typeof selectedRun) & { networkId?: string })?.networkId ||
    "";

  const isPowerFlowRun = runId.startsWith("pf_");

  const runContext = useMemo<StoredSimulationResult | null>(() => {
    if (!resolvedNetworkId || !runId || isPowerFlowRun) return null;
    return buildRunContext(
      resolvedNetworkId,
      runId,
      selectedNetwork?.name,
    );
  }, [resolvedNetworkId, runId, selectedNetwork?.name, isPowerFlowRun]);

  const loadResults = () => {
    if (!networkId || !runId) return;
    setState("loading");
    setProgress(0);
    const steps = [20, 45, 72, 100];
    let i = 0;
    const tick = () => {
      if (i >= steps.length) {
        setState("ready");
        return;
      }
      setProgress(steps[i++]);
      setTimeout(tick, 350);
    };
    setTimeout(tick, 200);
  };

  const reset = () => {
    setState("idle");
    setProgress(0);
  };

  // Auto-sync when arriving from another page with a runId in the URL
  useEffect(() => {
    if (!incomingRun) return;
    if (autoLoadedRef.current === incomingRun.id) return;
    autoLoadedRef.current = incomingRun.id;
    const scn = getAllScenarios().find((s) => s.id === incomingRun.scenarioId);
    const resolvedNetworkId =
      scn?.networkId ??
      (incomingRun as (typeof incomingRun) & { networkId?: string })?.networkId;
    if (resolvedNetworkId) setNetworkId(resolvedNetworkId);
    setRunId(incomingRun.id);
    setProgress(100);
    setState("ready");
  }, [incomingRun]);

  // For seeded runs arriving via URL: networkId comes from the run itself,
  // not from a scenario. Trigger auto-load once networkId is resolved.
  useEffect(() => {
    if (state !== "idle") return;
    if (!incomingRunId) return;
    const run = runs.find((r) => r.id === incomingRunId);
    if (!run) return;
    const resolvedNetworkId =
      (run as typeof run & { networkId?: string }).networkId ?? "";
    if (!resolvedNetworkId) return;
    if (autoLoadedRef.current === incomingRunId) return;
    autoLoadedRef.current = incomingRunId;
    setNetworkId(resolvedNetworkId);
    setRunId(incomingRunId);
    setProgress(100);
    setState("ready");
  }, [state, incomingRunId, runs]);

  // Direct link from OpenDSS run panel: runId + networkId in URL but run not in local store.
  useEffect(() => {
    if (!incomingRunId || !incomingNetworkId) return;
    if (incomingRun) return; // already handled above
    if (autoLoadedRef.current === incomingRunId) return;
    autoLoadedRef.current = incomingRunId;
    setNetworkId(incomingNetworkId);
    setRunId(incomingRunId);
    setProgress(100);
    setState("ready");
  }, [incomingRunId, incomingNetworkId, incomingRun]);

  const tooltipStyle = {
    backgroundColor: "var(--card)",
    border: "1px solid var(--border)",
    borderRadius: 6,
    fontSize: 12,
  };

  return (
    <AppShell>
      <PageHeader
        title="Results & Analytics"
        description="Select a run to load voltage and loading analytics."
      />

      {/* Selection panel */}
      <Card className="p-5 mb-6">
        <div className="flex items-center gap-2 mb-4">
          <BarChart3 className="h-4 w-4 text-primary" />
          <div className="text-sm font-semibold">Result selection</div>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <label className="text-xs uppercase tracking-wider text-muted-foreground font-medium mb-1.5 block">
              Network <span className="text-destructive">*</span>
            </label>
            <Select
              value={networkId}
              onValueChange={(v) => {
                setNetworkId(v);
                setRunId("");
                reset();
              }}
              disabled={state === "loading"}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select a network…" />
              </SelectTrigger>
              <SelectContent>
                {networks.map((n) => (
                  <SelectItem key={n.id} value={n.id}>
                    {n.name}{" "}
                    <span className="text-muted-foreground">· {n.voltage}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="text-xs uppercase tracking-wider text-muted-foreground font-medium mb-1.5 block">
              Simulation run <span className="text-destructive">*</span>
            </label>
            <Select
              value={runId}
              onValueChange={(v) => {
                setRunId(v);
                reset();
              }}
              disabled={!networkId || state === "loading"}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select a run…" />
              </SelectTrigger>
              <SelectContent>
                {networkRuns.length === 0 && (
                  <div className="px-2 py-3 text-xs text-muted-foreground">
                    No completed runs for this network.
                  </div>
                )}
                {networkRuns.map((r) => (
                  <SelectItem key={r.id} value={r.id}>
                    {r.id} · {r.scenarioName}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="flex items-center justify-between mt-5 pt-4 border-t border-border">
          <div className="text-xs text-muted-foreground">
            {selectedNetwork && selectedRun ? (
              <>
                {selectedNetwork.name} · {selectedRun.id}
                {runContext && (
                  <> · <span className="font-medium text-foreground">
                    {runContext.horizon === "month"
                      ? `${monthName(runContext.month)} ${runContext.year}`
                      : runContext.day
                      ? `${runContext.day} ${monthName(runContext.month)} ${runContext.year}`
                      : `${monthName(runContext.month)} ${runContext.year}`}
                  </span></>
                )}
                {" · started "}{selectedRun.startedAt}
              </>
            ) : (
              "Pick a network and a completed run."
            )}
          </div>
          <div className="flex items-center gap-2">
            {state === "ready" && (
              <Button variant="outline" size="sm" onClick={reset}>
                <RotateCcw className="h-3.5 w-3.5" /> Reset
              </Button>
            )}
            <Button
              onClick={loadResults}
              disabled={!networkId || !runId || state === "loading"}
            >
              {state === "loading" ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" /> Loading…
                </>
              ) : (
                <>
                  <Play className="h-4 w-4" /> Load Results
                </>
              )}
            </Button>
          </div>
        </div>
      </Card>

      {/* States */}
      {state === "idle" && (
        <Card className="p-10 text-center mb-6 border-dashed">
          <BarChart3 className="h-10 w-10 text-muted-foreground mx-auto mb-3" />
          <div className="text-base font-semibold mb-1">No results loaded</div>
          <div className="text-sm text-muted-foreground">
            Pick a network and a completed run, then press{" "}
            <span className="font-medium text-foreground">Load Results</span>.
          </div>
        </Card>
      )}

      {state === "loading" && (
        <Card className="p-6 mb-6">
          <div className="flex items-center gap-3 mb-4">
            <Loader2 className="h-5 w-5 text-primary animate-spin" />
            <div>
              <div className="text-sm font-semibold">Loading simulation results…</div>
              <div className="text-xs text-muted-foreground">
                Fetching voltages, line and transformer loadings.
              </div>
            </div>
            <div className="ml-auto text-sm font-mono">{progress}%</div>
          </div>
          <Progress value={progress} />
        </Card>
      )}

      {state === "ready" && (
        <>
          {isPowerFlowRun ? (
            /* Power flow: plot fills the topology slot; summary + violations stack in the right column */
            <div className="grid gap-3 lg:grid-cols-[2fr_1fr] mb-6">
              <PowerFlowPlotCard networkId={resolvedNetworkId} runId={runId} />
              <div className="flex flex-col gap-3">
                <PowerFlowSummaryCard runId={runId} selectedRun={selectedRun} />
                <PowerFlowViolationsCard networkId={resolvedNetworkId} runId={runId} />
              </div>
            </div>
          ) : (
            <>
              {/* Topology overview + Results View side by side */}
              <div className="grid gap-3 lg:grid-cols-[2fr_1fr] mb-6">
                <NetworkTopology
                  networkName={selectedNetwork?.name ?? "Network"}
                  networkId={selectedNetwork?.id ?? null}
                />
                <CurrentResultsView ctx={runContext} fallbackNetworkName={selectedNetwork?.name} fallbackRunId={runId} />
              </div>

              {runContext ? (
                <RealKpiCards ctx={runContext} />
              ) : (
                <EmptyDataCard
                  title="No KPI data"
                  hint="Run a simulation from the Scenario Builder to compute voltage and loading KPIs."
                />
              )}

              {runContext ? (
                <RealResultsTabs ctx={runContext} />
              ) : (
                <Card className="p-6 text-sm text-muted-foreground border-dashed">
                  No backend simulation result available in this session. Run a
                  simulation from the Scenario Builder to see real time-series
                  charts here.
                </Card>
              )}

              <ViolationDetectionSection
                runId={runContext?.runId ?? runId}
                networkName={runContext?.networkName ?? selectedNetwork?.name}
                runContext={runContext ?? undefined}
                autoRun
              />
            </>
          )}
        </>
      )}
    </AppShell>
  );
}

// ── Power-flow specific components ──────────────────────────────────────────

/** Small summary card shown in the top-right slot for power-flow runs. */
function PowerFlowSummaryCard({
  runId,
  selectedRun,
}: {
  runId: string;
  selectedRun: ReturnType<typeof useRuns>[number] | undefined;
}) {
  const violations = (selectedRun as (typeof selectedRun) & { violations?: number })?.violations ?? null;
  return (
    <Card className="p-5 h-full">
      <div className="text-sm font-semibold mb-3">Power Flow Run</div>
      <dl className="space-y-2 text-sm">
        <div className="flex items-center justify-between gap-2">
          <dt className="text-muted-foreground">Run ID</dt>
          <dd className="font-mono text-xs truncate">{runId}</dd>
        </div>
        {selectedRun?.startedAt && (
          <div className="flex items-center justify-between gap-2">
            <dt className="text-muted-foreground">Started</dt>
            <dd className="font-medium">{selectedRun.startedAt}</dd>
          </div>
        )}
        {selectedRun?.duration && (
          <div className="flex items-center justify-between gap-2">
            <dt className="text-muted-foreground">Duration</dt>
            <dd className="font-medium">{selectedRun.duration}</dd>
          </div>
        )}
        {violations !== null && (
          <div className="flex items-center justify-between gap-2">
            <dt className="text-muted-foreground">Violations</dt>
            <dd className={violations > 0 ? "font-semibold text-destructive" : "font-medium text-emerald-600"}>
              {violations > 0 ? violations : "None"}
            </dd>
          </div>
        )}
      </dl>
    </Card>
  );
}

/** pf_res_plotly interactive plot — occupies the topology slot on the left. */
function PowerFlowPlotCard({ networkId, runId }: { networkId: string; runId: string }) {
  const [pfHtml, setPfHtml] = useState<string | null>(null);
  const [plotLoading, setPlotLoading] = useState(true);
  const [plotError, setPlotError] = useState<string | null>(null);

  // Fetch HTML with the Bearer token and inject via srcDoc —
  // iframes cannot send Authorization headers directly.
  useEffect(() => {
    if (!networkId || !runId) return;
    setPlotLoading(true);
    setPlotError(null);
    apiFetch(`${API_BASE}/networks/${networkId}/results/${runId}/pf-plot`)
      .then((res) => {
        if (!res.ok) throw new Error(`Server returned ${res.status}`);
        return res.text();
      })
      .then((html) => { setPfHtml(html); setPlotLoading(false); })
      .catch((err) => {
        setPlotError(err instanceof Error ? err.message : "Failed to load plot");
        setPlotLoading(false);
      });
  }, [networkId, runId]);

  return (
    <Card className="p-0 overflow-hidden flex flex-col">
      <div className="px-5 pt-4 pb-2 text-sm font-semibold border-b border-border/60 flex items-center gap-2 shrink-0">
        <BarChart3 className="h-4 w-4 text-primary" />
        Power Flow Plot
      </div>
      <div className="relative flex-1 min-h-[750px]">
        {plotLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-muted/20">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        )}
        {plotError && !plotLoading && (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">
            {plotError}
          </div>
        )}
        {pfHtml && (
          <iframe
            key={runId}
            srcDoc={pfHtml}
            title="Power flow result"
            className="w-full h-full border-0 block"
            sandbox="allow-scripts"
          />
        )}
      </div>
    </Card>
  );
}

/** Violations breakdown card — stacks below the summary in the right column. */
function PowerFlowViolationsCard({ networkId, runId }: { networkId: string; runId: string }) {
  const [violations, setViolations] = useState<PowerFlowViolations | null>(null);
  const [violError, setViolError] = useState<string | null>(null);

  useEffect(() => {
    if (!networkId || !runId) return;
    fetchPfViolations(networkId, runId)
      .then(setViolations)
      .catch(() => setViolError("Could not load violation data."));
  }, [networkId, runId]);

  const ViolRow = ({ label, count }: { label: string; count: number }) => (
    <div className="flex items-center justify-between py-2 border-b border-border/50 last:border-0">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className={cn("text-sm font-semibold", count > 0 ? "text-destructive" : "text-emerald-600")}>
        {count}
      </span>
    </div>
  );

  return (
    <Card className="p-5">
      <div className="flex items-center gap-2 mb-4">
        {violations && violations.total === 0 ? (
          <CheckCircle2 className="h-4 w-4 text-emerald-600" />
        ) : (
          <AlertTriangle className="h-4 w-4 text-destructive" />
        )}
        <div className="text-sm font-semibold">Violation Detection</div>
        {violations && (
          <span className={cn(
            "ml-auto text-xs font-medium px-2 py-0.5 rounded-full",
            violations.total === 0
              ? "bg-emerald-500/10 text-emerald-600"
              : "bg-destructive/10 text-destructive",
          )}>
            {violations.total === 0 ? "No violations" : `${violations.total} violation${violations.total !== 1 ? "s" : ""}`}
          </span>
        )}
      </div>
      {violError ? (
        <p className="text-xs text-muted-foreground">{violError}</p>
      ) : violations ? (
        <div>
          <ViolRow label="Under-voltage buses (< 0.94 pu)"   count={violations.under_voltage} />
          <ViolRow label="Over-voltage buses (> 1.06 pu)"    count={violations.over_voltage} />
          <ViolRow label="Overloaded lines (> 100%)"          count={violations.line_overload} />
          <ViolRow label="Overloaded transformers (> 100%)"   count={violations.trafo_overload} />
        </div>
      ) : (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading violation data…
        </div>
      )}
    </Card>
  );
}

function CurrentResultsView({
  ctx,
  fallbackNetworkName,
  fallbackRunId,
}: {
  ctx: StoredSimulationResult | null;
  fallbackNetworkName?: string;
  fallbackRunId?: string;
}) {
  if (!ctx) {
    return (
      <Card className="p-5 h-full border-dashed">
        <div className="text-sm font-semibold mb-1">Current Results View</div>
        <div className="text-xs text-muted-foreground">
          No backend simulation has been run in this session yet. Run a simulation
          from the Scenario Builder to populate this section with real run context.
        </div>
        {(fallbackNetworkName || fallbackRunId) && (
          <div className="mt-3 text-xs text-muted-foreground">
            Showing mock data for{" "}
            <span className="font-mono">{fallbackNetworkName ?? "—"}</span>
            {" / "}
            <span className="font-mono">{fallbackRunId ?? "—"}</span>.
          </div>
        )}
      </Card>
    );
  }

  const horizonLabel =
    ctx.horizon === "day" ? "Day" : ctx.horizon === "week" ? "Week" : "Month";
  const isOpenDSS = ctx.networkId.startsWith("opendss-");
  const stepMinutes = isOpenDSS ? 30 : 15;
  const stepsPerDay = 24 * 60 / stepMinutes;
  const steps = isOpenDSS
    ? stepsPerDay   // OpenDSS always runs a single day
    : timeStepCount(ctx);
  const windowLabel = timeWindowLabel(ctx);

  const fields: { label: string; value: string; mono?: boolean }[] = [
    { label: "Network name", value: ctx.networkName ?? "—" },
    { label: "Network ID", value: ctx.networkId, mono: true },
    { label: "Run ID", value: ctx.runId, mono: true },
    { label: "Simulation horizon", value: horizonLabel },
    { label: "Mode", value: ctx.mode === "balanced" ? "Balanced" : "Unbalanced" },
    { label: "Year", value: String(ctx.year) },
    { label: "Month", value: `${monthName(ctx.month)} (${ctx.month})` },
  ];
  if (ctx.horizon === "day" || ctx.horizon === "week") {
    fields.push({ label: "Day", value: ctx.day != null ? String(ctx.day) : "—" });
  }
  fields.push({ label: "Time window", value: windowLabel });
  fields.push({ label: "Time steps", value: `${steps} (${stepMinutes}-min resolution)` });
  fields.push({ label: "Data source", value: "Backend simulation results" });

  return (
    <Card className="p-5 h-full">
      <div className="flex items-center gap-2 mb-1">
        <BarChart3 className="h-4 w-4 text-primary" />
        <div className="text-sm font-semibold">Current Results View</div>
      </div>
      <div className="text-xs text-muted-foreground mb-4">
        What you are viewing — derived from the latest backend run response.
      </div>
      <div className="grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
        {fields.map((f) => (
          <div key={f.label}>
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
              {f.label}
            </div>
            <div
              className={
                "mt-0.5 text-sm " + (f.mono ? "font-mono" : "font-medium")
              }
            >
              {f.value}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function EmptyDataCard({ title, hint }: { title: string; hint: string }) {
  return (
    <Card className="p-10 text-center mb-6 border-dashed">
      <BarChart3 className="h-10 w-10 text-muted-foreground mx-auto mb-3" />
      <div className="text-base font-semibold mb-1">{title}</div>
      <div className="text-sm text-muted-foreground">{hint}</div>
    </Card>
  );
}

function NetworkTopology({
  networkName,
  networkId,
  startedAt,
}: {
  networkName: string;
  networkId: string | null;
  startedAt?: string;
}) {
  const [failed, setFailed] = useState(false);
  // Cache-buster: force the browser to fetch the latest plot HTML on every
  // page visit instead of serving a stale version from its local cache.
  const src = networkId ? `${API_BASE}/plots/${networkId}.html?v=${Date.now()}` : null;

  useEffect(() => {
    setFailed(false);
  }, [networkId]);

  const isOpenDSS = networkId?.startsWith("opendss-") ?? false;

  return (
    <Card className={cn("p-0 flex flex-col", isOpenDSS ? "overflow-auto" : "overflow-hidden")}
      style={isOpenDSS ? undefined : { height: 720 }}>
      <div className="flex items-center justify-between px-5 pt-5 pb-3 shrink-0">
        <div>
          <div className="text-sm font-semibold">Topology overview</div>
          {startedAt && startedAt !== "—" && (
            <div className="text-xs text-muted-foreground mt-0.5">Simulation date: {startedAt}</div>
          )}
        </div>
        <div className="text-xs text-muted-foreground">{networkName}</div>
      </div>
      {src && !failed ? (
        isOpenDSS ? (
          <iframe
            key={src}
            src={src}
            title={`${networkName} topology`}
            style={{ width: 1012, height: 720, border: 0, display: "block" }}
            scrolling="no"
            onError={() => setFailed(true)}
          />
        ) : (
          <iframe
            key={src}
            src={src}
            title={`${networkName} topology`}
            className="w-full flex-1 border-0 block min-h-0"
            onError={() => setFailed(true)}
          />
        )
      ) : (
        <div className="flex-1 min-h-0 border-t border-dashed border-border bg-muted/30 flex items-center justify-center text-muted-foreground text-sm">
          <div className="text-center">
            <Cable className="h-10 w-10 mx-auto mb-2 opacity-40" />
            Topology plot not available for this network.
          </div>
        </div>
      )}
    </Card>
  );
}

// ============================================================================
// Real backend-driven results — uses aggregated endpoints (no full CSV download)
// ============================================================================

interface EnvState {
  loading: boolean;
  error: string | null;
  data: EnvelopeResult | null;
}

interface PhaseState {
  loading: boolean;
  error: string | null;
  data: PhasesResult | null;
}

const PHASE_COLORS = {
  a: "oklch(0.58 0.22 25)",
  b: "oklch(0.62 0.16 150)",
  c: "oklch(0.55 0.20 260)",
};

function useResultEnvelope(networkId: string, runId: string, kind: ResultKind, enabled = true): EnvState {
  const [state, setState] = useState<EnvState>({ loading: true, error: null, data: null });
  useEffect(() => {
    if (!enabled) {
      setState({ loading: false, error: null, data: null });
      return;
    }
    let cancelled = false;
    setState({ loading: true, error: null, data: null });
    fetchResultEnvelope(networkId, runId, kind)
      .then((d) => { if (!cancelled) setState({ loading: false, error: null, data: d }); })
      .catch((e: Error) => { if (!cancelled) setState({ loading: false, error: e.message, data: null }); });
    return () => { cancelled = true; };
  }, [networkId, runId, kind, enabled]);
  return state;
}

function useResultPhases(networkId: string, runId: string, kind: ResultKind, enabled: boolean): PhaseState {
  const [state, setState] = useState<PhaseState>({ loading: true, error: null, data: null });
  useEffect(() => {
    if (!enabled) {
      setState({ loading: false, error: null, data: null });
      return;
    }
    let cancelled = false;
    setState({ loading: true, error: null, data: null });
    fetchResultPhases(networkId, runId, kind)
      .then((d) => { if (!cancelled) setState({ loading: false, error: null, data: d }); })
      .catch((e: Error) => { if (!cancelled) setState({ loading: false, error: e.message, data: null }); });
    return () => { cancelled = true; };
  }, [networkId, runId, kind, enabled]);
  return state;
}

function fmtEnv(state: EnvState, mode: "min" | "max", decimals: number): string {
  if (state.loading) return "…";
  if (state.error || !state.data) return "N/A";
  const arr = mode === "min" ? state.data.min : state.data.max;
  if (arr.length === 0) return "N/A";
  const v = mode === "min" ? Math.min(...arr) : Math.max(...arr);
  return Number.isFinite(v) ? v.toFixed(decimals) : "N/A";
}

function phaseGlobalMin(state: PhaseState, decimals: number): string {
  if (state.loading) return "…";
  if (state.error || !state.data) return "N/A";
  const { a, b, c } = state.data;
  const v = Math.min(...a.min, ...b.min, ...c.min);
  return Number.isFinite(v) ? v.toFixed(decimals) : "N/A";
}

function phaseGlobalMax(state: PhaseState, decimals: number): string {
  if (state.loading) return "…";
  if (state.error || !state.data) return "N/A";
  const { a, b, c } = state.data;
  const v = Math.max(...a.max, ...b.max, ...c.max);
  return Number.isFinite(v) ? v.toFixed(decimals) : "N/A";
}

function RealKpiCards({ ctx }: { ctx: StoredSimulationResult }) {
  const isUnbalanced = ctx.networkId.endsWith("-unbalanced");

  const vm = useResultEnvelope(ctx.networkId, ctx.runId, "vm-pu", !isUnbalanced);
  const ll = useResultEnvelope(ctx.networkId, ctx.runId, "line-loading", !isUnbalanced);
  const tl = useResultEnvelope(ctx.networkId, ctx.runId, "trafo-loading");

  const vmPhases = useResultPhases(ctx.networkId, ctx.runId, "vm-pu", isUnbalanced);
  const llPhases = useResultPhases(ctx.networkId, ctx.runId, "line-loading", isUnbalanced);
  const tlPhases = useResultPhases(ctx.networkId, ctx.runId, "trafo-loading", isUnbalanced);

  const cards = isUnbalanced
    ? [
        { label: "Min voltage",      value: phaseGlobalMin(vmPhases, 4), unit: "pu", icon: TrendingDown, tone: "text-destructive" },
        { label: "Max voltage",      value: phaseGlobalMax(vmPhases, 4), unit: "pu", icon: TrendingUp,   tone: "text-warning-foreground" },
        { label: "Max line loading", value: phaseGlobalMax(llPhases, 1), unit: "%",  icon: Cable,        tone: "text-info" },
        { label: "Max trafo loading",value: phaseGlobalMax(tlPhases, 1), unit: "%",  icon: Zap,          tone: "text-primary" },
      ]
    : [
        { label: "Min voltage",      value: fmtEnv(vm, "min", 4), unit: "pu", icon: TrendingDown, tone: "text-destructive" },
        { label: "Max voltage",      value: fmtEnv(vm, "max", 4), unit: "pu", icon: TrendingUp,   tone: "text-warning-foreground" },
        { label: "Max line loading", value: fmtEnv(ll, "max", 1), unit: "%",  icon: Cable,        tone: "text-info" },
        { label: "Max trafo loading",value: fmtEnv(tl, "max", 1), unit: "%",  icon: Zap,          tone: "text-primary" },
      ];

  return (
    <div className="grid gap-4 grid-cols-2 lg:grid-cols-4 mb-6">
      {cards.map((k) => {
        const Icon = k.icon;
        return (
          <Card key={k.label} className="p-5">
            <div className="flex items-start justify-between">
              <div>
                <div className="text-xs uppercase tracking-wider text-muted-foreground font-medium">
                  {k.label}
                </div>
                <div className="mt-2 text-2xl md:text-3xl font-semibold tabular-nums">
                  {k.value}{" "}
                  <span className="text-sm font-normal text-muted-foreground">{k.unit}</span>
                </div>
              </div>
              <div className={"rounded-md bg-muted p-2 " + k.tone}>
                <Icon className="h-4 w-4" />
              </div>
            </div>
          </Card>
        );
      })}
    </div>
  );
}

function RealResultsTabs({ ctx }: { ctx: StoredSimulationResult }) {
  const isUnbalanced = ctx.networkId.endsWith("-unbalanced");
  const isOpenDSS    = ctx.networkId.startsWith("opendss-");

  const vm = useResultEnvelope(ctx.networkId, ctx.runId, "vm-pu", !isUnbalanced);
  const ll = useResultEnvelope(ctx.networkId, ctx.runId, "line-loading", !isUnbalanced);
  const tl = useResultEnvelope(ctx.networkId, ctx.runId, "trafo-loading");

  const vmPhases = useResultPhases(ctx.networkId, ctx.runId, "vm-pu", isUnbalanced);
  const llPhases = useResultPhases(ctx.networkId, ctx.runId, "line-loading", isUnbalanced);
  const tlPhases = useResultPhases(ctx.networkId, ctx.runId, "trafo-loading", isUnbalanced);

  return (
    <Tabs defaultValue="voltages">
      <TabsList>
        <TabsTrigger value="voltages">Bus Voltage</TabsTrigger>
        <TabsTrigger value="lines">Line Loading</TabsTrigger>
        <TabsTrigger value="trafos">Transformer Loading</TabsTrigger>
        <TabsTrigger value="explorer">Component Explorer</TabsTrigger>
      </TabsList>

      <TabsContent value="voltages" className="mt-4">
        <EnvelopeChart
          title="Bus voltage envelope"
          subtitle={
            isUnbalanced
              ? "Mean vm_pu per phase (A / B / C) across all buses"
              : isOpenDSS
              ? "Mean vm_pu across all buses"
              : "Min / mean / max vm_pu across all buses"
          }
          state={vm} ctx={ctx} unit=" pu" yDomain={[0.9, 1.1]} showMin
          meanOnly={isOpenDSS && !isUnbalanced}
          phaseState={isUnbalanced ? vmPhases : undefined}
          thresholds={[{ y: 0.94, label: "0.94" }, { y: 1.06, label: "1.06" }]}
        />
      </TabsContent>
      <TabsContent value="lines" className="mt-4">
        <EnvelopeChart
          title="Line loading"
          subtitle={
            isUnbalanced
              ? "Mean loading_percent per phase (A / B / C) across all lines"
              : isOpenDSS
              ? "Mean loading_percent across all lines"
              : "Mean / max loading_percent across all lines"
          }
          state={ll} ctx={ctx} unit="%" yDomain={[0, "auto"]}
          meanOnly={isOpenDSS && !isUnbalanced}
          phaseState={isUnbalanced ? llPhases : undefined}
          thresholds={[{ y: 100, label: "100%" }]}
        />
      </TabsContent>
      <TabsContent value="trafos" className="mt-4">
        <EnvelopeChart
          title="Transformer loading"
          subtitle={
            isUnbalanced
              ? "Mean loading_percent per phase (A / B / C) across all transformers"
              : isOpenDSS
              ? "Mean loading_percent across all transformers"
              : "Mean / max loading_percent across all transformers"
          }
          state={tl} ctx={ctx} unit="%" yDomain={[0, "auto"]}
          meanOnly={isOpenDSS && !isUnbalanced}
          phaseState={isUnbalanced ? tlPhases : undefined}
          thresholds={[{ y: 100, label: "100%" }]}
        />
      </TabsContent>
      <TabsContent value="explorer" className="mt-4">
        <RealComponentExplorer
          ctx={ctx} vm={vm} ll={ll} tl={tl}
          vmPhases={vmPhases} llPhases={llPhases} tlPhases={tlPhases}
        />
      </TabsContent>
    </Tabs>
  );
}

interface EnvelopeChartProps {
  title: string;
  subtitle: string;
  state: EnvState;
  ctx: StoredSimulationResult;
  unit: string;
  yDomain: [number | string, number | string];
  showMin?: boolean;
  meanOnly?: boolean;
  thresholds: { y: number; label: string }[];
  phaseState?: PhaseState;
}

function EnvelopeChart({ title, subtitle, state, ctx, unit, yDomain, showMin, meanOnly, thresholds, phaseState }: EnvelopeChartProps) {
  const tooltipStyle = {
    backgroundColor: "var(--card)",
    border: "1px solid var(--border)",
    borderRadius: 6,
    fontSize: 12,
  };

  const stepMinutes = ctx.networkId.startsWith("opendss-") ? 30 : 15;
  const usePhaseData = !!phaseState;

  const data = useMemo(() => {
    if (!state.data) return [];
    const { min, mean, max } = state.data;
    const ts = generateTimestamps(ctx, min.length, stepMinutes);
    return min.map((mn, i) => ({
      t: ts[i].getTime(),
      label: formatAxisTick(ts[i], ctx.horizon),
      full: formatFullTimestamp(ts[i]),
      min:  Number.isFinite(mn)      ? +mn.toFixed(4)      : null,
      mean: Number.isFinite(mean[i]) ? +mean[i].toFixed(4) : null,
      max:  Number.isFinite(max[i])  ? +max[i].toFixed(4)  : null,
    }));
  }, [state.data, ctx, stepMinutes]);

  const phaseData = useMemo(() => {
    if (!phaseState?.data) return [];
    const { a, b, c } = phaseState.data;
    const n = a.mean.length;
    const ts = generateTimestamps(ctx, n, stepMinutes);
    return Array.from({ length: n }, (_, i) => ({
      t: ts[i].getTime(),
      label: formatAxisTick(ts[i], ctx.horizon),
      full: formatFullTimestamp(ts[i]),
      meanA: Number.isFinite(a.mean[i]) ? +a.mean[i].toFixed(4) : null,
      meanB: Number.isFinite(b.mean[i]) ? +b.mean[i].toFixed(4) : null,
      meanC: Number.isFinite(c.mean[i]) ? +c.mean[i].toFixed(4) : null,
    }));
  }, [phaseState?.data, ctx, stepMinutes]);

  const activeData = usePhaseData ? phaseData : data;
  const isLoading  = usePhaseData ? phaseState!.loading : state.loading;
  const activeError = usePhaseData ? phaseState!.error  : state.error;
  const isVoltage  = unit === " pu";

  const computedDomain = useMemo<[number | string, number | string]>(() => {
    if (!isVoltage) return yDomain;
    const values: number[] = [];
    if (usePhaseData) {
      for (const d of phaseData) {
        if (d.meanA != null) values.push(d.meanA);
        if (d.meanB != null) values.push(d.meanB);
        if (d.meanC != null) values.push(d.meanC);
      }
    } else {
      for (const d of data) {
        if (d.min != null) values.push(d.min);
        if (d.mean != null) values.push(d.mean);
        if (d.max != null) values.push(d.max);
      }
    }
    if (values.length === 0) return yDomain;
    const lo = Math.min(...values), hi = Math.max(...values);
    const range = Math.max(hi - lo, 0.01);
    const pad = Math.max(range * 0.15, 0.005);
    return [+(lo - pad).toFixed(3), +(hi + pad).toFixed(3)];
  }, [data, phaseData, isVoltage, yDomain, usePhaseData]);

  const visibleThresholds = useMemo(() => {
    if (!isVoltage) return thresholds;
    const [lo, hi] = computedDomain as [number, number];
    return thresholds.filter((th) => th.y >= lo && th.y <= hi);
  }, [thresholds, computedDomain, isVoltage]);

  const tickInterval = Math.max(0, Math.floor(activeData.length / 8) - 1);

  return (
    <Card className="p-5">
      <div className="mb-4">
        <div className="text-sm font-semibold mb-1">{title}</div>
        <div className="text-xs text-muted-foreground">{subtitle}</div>
      </div>

      {isLoading && (
        <div className="h-72 flex items-center justify-center text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin mr-2" /> Loading…
        </div>
      )}
      {!isLoading && activeError && (
        <div className="h-72 flex items-center justify-center text-sm text-destructive text-center px-4">
          {activeError}
        </div>
      )}
      {!isLoading && !activeError && activeData.length === 0 && (
        <div className="h-72 flex items-center justify-center text-sm text-muted-foreground">
          No data points returned.
        </div>
      )}
      {!isLoading && !activeError && activeData.length > 0 && (
        <div className="h-80">
          <ResponsiveContainer>
            <LineChart data={activeData as object[]} margin={{ top: 5, right: 48, left: -10, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.91 0.01 240)" />
              <XAxis
                dataKey="t" type="number" scale="time"
                domain={["dataMin", "dataMax"]}
                stroke="oklch(0.5 0.02 250)" fontSize={11}
                interval={tickInterval} minTickGap={20}
                tickFormatter={(v) => formatAxisTick(new Date(Number(v)), ctx.horizon)}
              />
              <YAxis
                stroke="oklch(0.5 0.02 250)" fontSize={11}
                domain={computedDomain}
                unit={unit === " pu" ? "" : unit}
              />
              <Tooltip
                contentStyle={tooltipStyle}
                labelFormatter={(_label, payload) => {
                  const p = payload?.[0]?.payload as { full?: string } | undefined;
                  return p?.full ?? String(_label);
                }}
                formatter={(value, name) => [`${value}${unit}`, String(name)]}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {visibleThresholds.map((th) => (
                <ReferenceLine key={th.y} y={th.y} stroke="oklch(0.58 0.22 25)" strokeDasharray="4 4"
                  label={{ value: th.label, position: "right", fill: "oklch(0.58 0.22 25)", fontSize: 11 }}
                />
              ))}
              {usePhaseData ? (
                <>
                  <Line dataKey="meanA" stroke={PHASE_COLORS.a} strokeWidth={2} dot={false} name="Phase A" />
                  <Line dataKey="meanB" stroke={PHASE_COLORS.b} strokeWidth={2} dot={false} name="Phase B" />
                  <Line dataKey="meanC" stroke={PHASE_COLORS.c} strokeWidth={2} dot={false} name="Phase C" />
                </>
              ) : (
                <>
                  {showMin && !meanOnly && <Line dataKey="min" stroke="oklch(0.58 0.22 25)" strokeWidth={2} dot={false} name="Min" />}
                  <Line dataKey="mean" stroke="oklch(0.62 0.16 150)" strokeWidth={2} dot={false} name="Mean" />
                  {!meanOnly && <Line dataKey="max" stroke="oklch(0.7 0.12 80)" strokeWidth={1.5} dot={false} name="Max" />}
                </>
              )}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}

function ComponentCombobox({
  columns, value, onChange, loading, placeholder,
}: {
  columns: string[];
  value: string;
  onChange: (v: string) => void;
  loading: boolean;
  placeholder: string;
}) {
  const [open, setOpen] = useState(false);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          disabled={loading || columns.length === 0}
          className="w-full justify-between font-normal"
        >
          <span className="truncate text-left">
            {value || (loading ? "Loading…" : columns.length === 0 ? "No data" : placeholder)}
          </span>
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[--radix-popover-trigger-width] p-0" align="start">
        <Command>
          <CommandInput placeholder="Search…" className="h-9" />
          <CommandList>
            <CommandEmpty>No match.</CommandEmpty>
            <CommandGroup>
              {columns.map((c) => (
                <CommandItem
                  key={c}
                  value={c}
                  onSelect={(v) => { onChange(v); setOpen(false); }}
                >
                  <Check className={cn("mr-2 h-4 w-4 shrink-0", value === c ? "opacity-100" : "opacity-0")} />
                  {c}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

function RealComponentExplorer({
  ctx, vm, ll, tl, vmPhases, llPhases, tlPhases,
}: {
  ctx: StoredSimulationResult;
  vm: EnvState; ll: EnvState; tl: EnvState;
  vmPhases: PhaseState; llPhases: PhaseState; tlPhases: PhaseState;
}) {
  type Kind = "bus" | "line" | "trafo";
  const isUnbalanced = ctx.networkId.endsWith("-unbalanced");

  const [kind, setKind]   = useState<Kind>("bus");
  const [name, setName]   = useState<string>("");
  const [colLoading, setColLoading] = useState(false);
  const [colError,   setColError]   = useState<string | null>(null);
  const [colValues,  setColValues]  = useState<number[] | null>(null);
  const [phaseColValues, setPhaseColValues] = useState<{ a: number[]; b: number[]; c: number[] } | null>(null);

  const source      = kind === "bus" ? vm       : kind === "line" ? ll       : tl;
  const phaseSource = kind === "bus" ? vmPhases : kind === "line" ? llPhases : tlPhases;
  const kindLabel   = kind === "bus" ? "Bus" : kind === "line" ? "Line" : "Transformer";
  const resultKind: ResultKind = kind === "bus" ? "vm-pu" : kind === "line" ? "line-loading" : "trafo-loading";
  const unit        = kind === "bus" ? " pu" : "%";

  const columns     = isUnbalanced
    ? (phaseSource.data?.a.columns ?? [])
    : (source.data?.columns ?? []);
  const colsLoading = isUnbalanced ? phaseSource.loading : source.loading;

  // Reset on kind change
  useEffect(() => { setName(""); setColValues(null); setPhaseColValues(null); }, [kind]);

  // Fetch column data on name selection
  useEffect(() => {
    if (!name) return;
    let cancelled = false;
    setColLoading(true); setColError(null); setColValues(null); setPhaseColValues(null);
    if (isUnbalanced) {
      fetchResultPhasesColumn(ctx.networkId, ctx.runId, resultKind, name)
        .then((d) => { if (!cancelled) { setPhaseColValues({ a: d.a, b: d.b, c: d.c }); setColLoading(false); } })
        .catch((e: Error) => { if (!cancelled) { setColError(e.message); setColLoading(false); } });
    } else {
      fetchResultColumn(ctx.networkId, ctx.runId, resultKind, name)
        .then((d) => { if (!cancelled) { setColValues(d.values); setColLoading(false); } })
        .catch((e: Error) => { if (!cancelled) { setColError(e.message); setColLoading(false); } });
    }
    return () => { cancelled = true; };
  }, [ctx.networkId, ctx.runId, resultKind, name, isUnbalanced]);

  const tooltipStyle = {
    backgroundColor: "var(--card)",
    border: "1px solid var(--border)",
    borderRadius: 6,
    fontSize: 12,
  };

  const stepMinutes = ctx.networkId.startsWith("opendss-") ? 30 : 15;

  // Balanced: single-value series
  const series = useMemo(() => {
    if (!colValues || !name) return [];
    const ts = generateTimestamps(ctx, colValues.length, stepMinutes);
    return colValues.map((v, i) => ({
      t: ts[i].getTime(),
      label: formatAxisTick(ts[i], ctx.horizon),
      full: formatFullTimestamp(ts[i]),
      value: Number.isFinite(v) ? +v.toFixed(4) : null,
    }));
  }, [colValues, name, ctx, stepMinutes]);

  // Unbalanced: per-phase series
  const phaseSeries = useMemo(() => {
    if (!phaseColValues || !name) return [];
    const n = phaseColValues.a.length;
    const ts = generateTimestamps(ctx, n, stepMinutes);
    return Array.from({ length: n }, (_, i) => ({
      t: ts[i].getTime(),
      label: formatAxisTick(ts[i], ctx.horizon),
      full: formatFullTimestamp(ts[i]),
      valueA: Number.isFinite(phaseColValues.a[i]) ? +phaseColValues.a[i].toFixed(4) : null,
      valueB: Number.isFinite(phaseColValues.b[i]) ? +phaseColValues.b[i].toFixed(4) : null,
      valueC: Number.isFinite(phaseColValues.c[i]) ? +phaseColValues.c[i].toFixed(4) : null,
    }));
  }, [phaseColValues, name, ctx, stepMinutes]);

  const activeSeries  = isUnbalanced ? phaseSeries : series;
  const tickInterval  = Math.max(0, Math.floor(activeSeries.length / 8) - 1);

  const stats = useMemo(() => {
    if (isUnbalanced && phaseColValues) {
      const all = [...phaseColValues.a, ...phaseColValues.b, ...phaseColValues.c].filter(Number.isFinite);
      if (all.length === 0) return null;
      const min = Math.min(...all), max = Math.max(...all);
      return { min: +min.toFixed(4), max: +max.toFixed(4), avg: +(all.reduce((a, b) => a + b, 0) / all.length).toFixed(4) };
    }
    const vals = series.map((s) => s.value).filter((v): v is number => v !== null);
    if (vals.length === 0) return null;
    const min = Math.min(...vals), max = Math.max(...vals);
    return { min, max, avg: +(vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(4) };
  }, [series, phaseColValues, isUnbalanced]);

  return (
    <Card className="p-5">
      <div className="flex items-center gap-2 mb-1">
        <Microscope className="h-4 w-4 text-primary" />
        <div className="text-sm font-semibold">Component Explorer</div>
      </div>
      <div className="text-xs text-muted-foreground mb-4">
        {isUnbalanced
          ? "Plot per-phase values for a single bus, line, or transformer."
          : "Plot a single bus, line, or transformer from the simulation result."}
      </div>

      <div className="grid gap-4 md:grid-cols-[180px_1fr] md:items-end">
        <div>
          <label className="text-xs uppercase tracking-wider text-muted-foreground font-medium mb-1.5 block">
            Component type
          </label>
          <Select value={kind} onValueChange={(v) => setKind(v as Kind)}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="bus">Bus</SelectItem>
              <SelectItem value="line">Line</SelectItem>
              <SelectItem value="trafo">Transformer</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div>
          <label className="text-xs uppercase tracking-wider text-muted-foreground font-medium mb-1.5 block">
            {kindLabel}
          </label>
          <ComponentCombobox
            columns={columns}
            value={name}
            onChange={setName}
            loading={colsLoading}
            placeholder={`Select ${kindLabel.toLowerCase()}…`}
          />
        </div>
      </div>

      {!name && (
        <div className="mt-6 rounded-md border border-dashed border-border p-8 text-center">
          <Microscope className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
          <div className="text-sm font-medium">No component plotted</div>
          <div className="text-xs text-muted-foreground mt-1">
            Pick a {kindLabel.toLowerCase()} above to see its time-series.
          </div>
        </div>
      )}

      {name && colLoading && (
        <div className="mt-6 h-16 flex items-center justify-center text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin mr-2" /> Loading…
        </div>
      )}

      {name && colError && (
        <div className="mt-4 text-sm text-destructive">{colError}</div>
      )}

      {name && activeSeries.length > 0 && (
        <div className="mt-6 space-y-4">
          {stats && (
            <div className="grid gap-3 grid-cols-3">
              {[
                { label: "Min", value: stats.min },
                { label: "Avg", value: stats.avg },
                { label: "Max", value: stats.max },
              ].map((s) => (
                <div key={s.label} className="rounded-md border border-border bg-muted/30 p-3">
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">{s.label}</div>
                  <div className="mt-1 text-xl font-semibold tabular-nums">
                    {s.value}
                    <span className="text-xs font-normal text-muted-foreground ml-1">{unit}</span>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="h-80">
            <ResponsiveContainer>
              <LineChart data={activeSeries as object[]} margin={{ top: 5, right: 48, left: -10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.91 0.01 240)" />
                <XAxis
                  dataKey="t" type="number" scale="time"
                  domain={["dataMin", "dataMax"]}
                  stroke="oklch(0.5 0.02 250)" fontSize={11}
                  interval={tickInterval} minTickGap={20}
                  tickFormatter={(v) => formatAxisTick(new Date(Number(v)), ctx.horizon)}
                />
                <YAxis
                  stroke="oklch(0.5 0.02 250)" fontSize={11}
                  domain={kind === "bus" ? [0.9, 1.1] : [0, "auto"]}
                  unit={kind === "bus" ? "" : "%"}
                />
                <Tooltip
                  contentStyle={tooltipStyle}
                  labelFormatter={(_label, payload) => {
                    const p = payload?.[0]?.payload as { full?: string } | undefined;
                    return p?.full ?? String(_label);
                  }}
                  formatter={(value, name) => [`${value}${unit}`, String(name)]}
                />
                {isUnbalanced && <Legend wrapperStyle={{ fontSize: 12 }} />}
                {kind === "bus" && (
                  <>
                    <ReferenceLine y={0.94} stroke="oklch(0.58 0.22 25)" strokeDasharray="4 4" />
                    <ReferenceLine y={1.06} stroke="oklch(0.58 0.22 25)" strokeDasharray="4 4" />
                  </>
                )}
                {kind !== "bus" && <ReferenceLine y={100} stroke="oklch(0.58 0.22 25)" strokeDasharray="4 4" />}
                {isUnbalanced ? (
                  <>
                    <Line dataKey="valueA" stroke={PHASE_COLORS.a} strokeWidth={2} dot={false} name="Phase A" />
                    <Line dataKey="valueB" stroke={PHASE_COLORS.b} strokeWidth={2} dot={false} name="Phase B" />
                    <Line dataKey="valueC" stroke={PHASE_COLORS.c} strokeWidth={2} dot={false} name="Phase C" />
                  </>
                ) : (
                  <Line
                    dataKey="value"
                    stroke={kind === "bus" ? "oklch(0.55 0.18 240)" : kind === "line" ? "oklch(0.72 0.18 60)" : "oklch(0.62 0.16 150)"}
                    strokeWidth={2} dot={false} name={`${kindLabel} ${name}`}
                  />
                )}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </Card>
  );
}