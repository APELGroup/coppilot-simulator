import { createFileRoute, Link } from "@tanstack/react-router";
import { useState, useEffect } from "react";
import { AppShell, PageHeader } from "@/components/app-shell";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import type { Scenario } from "@/lib/mock-data";
import { useScenarios, createScenario } from "@/lib/scenarios-store";
import { getCurrentUserInfo } from "@/lib/auth";
import { createRun, removeRun, updateRun } from "@/lib/runs-store";
import { enqueue } from "@/lib/sim-queue";
import { useNetworks } from "@/lib/networks-store";
import {
  runSimulation,
  runOpenDSSSimulation,
  runPowerFlow,
  type OpenDSSRunResult,
  API_BASE,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import {
  Play, Wand2, Layers, CalendarClock, Loader2, Clock,
  CheckCircle2, AlertCircle, BarChart3,
} from "lucide-react";

export const Route = createFileRoute("/scenarios")({
  validateSearch: (search: Record<string, unknown>): { networkId?: string } => {
    const nid = typeof search.networkId === "string" ? search.networkId : undefined;
    return nid ? { networkId: nid } : {};
  },
  head: () => ({
    meta: [
      { title: "Scenario Builder — DT Lab" },
      { name: "description", content: "Configure simulation scenarios for distribution networks." },
    ],
  }),
  component: ScenarioBuilder,
});

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

type Mode = "balanced" | "unbalanced";
type Horizon = "day" | "week" | "month";
type SimType = "time_series" | "power_flow";

type SubmitPhase = "idle" | "queued" | "running";

type OpenDSSRunState =
  | { phase: "idle" }
  | { phase: "queued" }
  | { phase: "running" }
  | { phase: "done"; result: OpenDSSRunResult }
  | { phase: "error"; message: string };

/** Convert a calendar date to a 1-based day-of-year (1–366).
 *  Uses Date.UTC to avoid DST-offset errors in local-time Date constructors. */
function toDayOfYear(y: number, m: number, d: number): number {
  const start = Date.UTC(y, 0, 0);   // Dec 31 of (y-1), midnight UTC
  const date  = Date.UTC(y, m - 1, d);
  return Math.round((date - start) / 86_400_000);
}

function ScenarioBuilder() {
  const networks = useNetworks();
  const scenarios = useScenarios();
  const { networkId: presetNetworkId } = Route.useSearch();

  const [name, setName] = useState("New scenario");
  const initialNetworkId =
    presetNetworkId && networks.some((n) => n.id === presetNetworkId)
      ? presetNetworkId
      : (networks[0]?.id ?? "");
  const [networkId, setNetworkId] = useState(initialNetworkId);
  const [mode, setMode] = useState<Mode>("balanced");
  const [horizon, setHorizon] = useState<Horizon>("day");

  const [year, setYear] = useState<number>(2016);
  const [month, setMonth] = useState("1");
  const [day, setDay] = useState("1");

  const [submitPhase, setSubmitPhase] = useState<SubmitPhase>("idle");
  const [lastRunId, setLastRunId] = useState<string | null>(null);

  // ── Simulation type toggle ──────────────────────────────────────────────────
  const [simType, setSimType] = useState<SimType>("time_series");
  const [pfTime, setPfTime]   = useState("12:00"); // combined HH:MM for power flow

  // ── OpenDSS-specific state ──────────────────────────────────────────────────
  const [opendssRunState, setOpendssRunState] = useState<OpenDSSRunState>({ phase: "idle" });

  const isOpenDSSNetwork = networkId.startsWith("opendss-");
  const opendssMode = isOpenDSSNetwork ? networkId.split("-")[2] : null;

  // OpenDSS data covers year 2014 (non-leap); SimBench uses 2016.
  useEffect(() => {
    setYear(isOpenDSSNetwork ? 2014 : 2016);
  }, [isOpenDSSNetwork]);

  // ── Standard SimBench handler ───────────────────────────────────────────────
  // ── Standard SimBench handler ───────────────────────────────────────────────
  const handleRun = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!networkId) { toast.error("Please select a network"); return; }
    setLastRunId(null);

    const tempRunId = `run-pending-${Date.now()}`;
    const pendingScenario: Scenario = {
      id: `scn-${Date.now()}`,
      name,
      networkId,
      simType: "time_series",
      mode,
      horizon,
      timestep: "—",
      createdBy: getCurrentUserInfo()?.name ?? "unknown",
      createdAt: new Date().toISOString().slice(0, 10),
    };
    await createScenario(pendingScenario);

    // Capture loop variables for the closure
    const _networkId = networkId;
    const _horizon   = horizon;
    const _year      = year;
    const _month     = month;
    const _day       = day;
    const _networks  = networks;

    const initialStatus = enqueue(async () => {
      updateRun(tempRunId, { status: "running" });
      setSubmitPhase("running");
      try {
        const result = await runSimulation({
          networkId: _networkId,
          horizon: _horizon,
          year: _year,
          month: Number(_month),
          day: _horizon === "month" ? undefined : Number(_day),
        });

        const candidate = (result && typeof result === "object" ? result : {}) as Record<string, unknown>;
        const runId =
          (typeof candidate.run_id === "string" && candidate.run_id) ||
          (typeof candidate.runId === "string" && candidate.runId) ||
          (typeof candidate.id === "string" && candidate.id) ||
          null;

        if (!runId) throw new Error("Backend did not return a run_id");

        setLastRunId(runId);

        toast.success(`Simulation completed — run ${runId}`);
        removeRun(tempRunId);
        createRun({
          scenarioId: pendingScenario.id,
          scenarioName: pendingScenario.name,
          networkName: _networks.find((n) => n.id === _networkId)?.name,
          runId,
          networkId: _networkId,
          createdBy: pendingScenario.createdBy,
          startedAtIso: typeof candidate.started_at === "string" ? candidate.started_at : undefined,
          durationSeconds: typeof candidate.duration_seconds === "number" ? candidate.duration_seconds : undefined,
          violations: typeof candidate.violations === "object" && candidate.violations !== null
            ? ((candidate.violations as Record<string, unknown>).total as number | undefined) ?? 0
            : 0,
        });
      } catch (err) {
        updateRun(tempRunId, { status: "failed" });
        console.error(err);
        toast.error(err instanceof Error ? err.message : "Could not reach the simulation service");
      } finally {
        setSubmitPhase("idle");
      }
    });

    createRun({
      scenarioId: pendingScenario.id,
      scenarioName: pendingScenario.name,
      networkName: networks.find((n) => n.id === networkId)?.name,
      runId: tempRunId,
      networkId,
      status: initialStatus,
      createdBy: pendingScenario.createdBy,
    });

    setSubmitPhase(initialStatus);
    if (initialStatus === "queued") {
      toast.info("Simulation queued — will start when the current run finishes.");
    }
  };

  // ── OpenDSS handler ─────────────────────────────────────────────────────────
  const handleOpenDSSRun = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!networkId) { toast.error("Please select a network"); return; }

    const tempRunId = `run-pending-${Date.now()}`;
    const pendingScenario: Scenario = {
      id: `scn-${Date.now()}`,
      name,
      networkId,
      simType: "time_series",
      mode: (opendssMode ?? "balanced") as "balanced" | "unbalanced",
      horizon: "day",
      timestep: "—",
      createdBy: getCurrentUserInfo()?.name ?? "unknown",
      createdAt: new Date().toISOString().slice(0, 10),
    };
    await createScenario(pendingScenario);

    // Capture loop variables for the closure
    const _networkId = networkId;
    const _year      = year;
    const _month     = month;
    const _day       = day;
    const _networks  = networks;

    const initialStatus = enqueue(async () => {
      updateRun(tempRunId, { status: "running" });
      setOpendssRunState({ phase: "running" });
      try {
        const doy = toDayOfYear(_year, Number(_month), Number(_day));
        const result = await runOpenDSSSimulation(_networkId, doy);
        setOpendssRunState({ phase: "done", result });
        toast.success(`Simulation completed — run ${result.run_id}`);
        removeRun(tempRunId);
        createRun({
          scenarioId: pendingScenario.id,
          scenarioName: pendingScenario.name,
          networkName: _networks.find((n) => n.id === _networkId)?.name,
          runId: result.run_id,
          networkId: _networkId,
          createdBy: pendingScenario.createdBy,
          durationSeconds: result.duration_seconds,
          violations:
            (result.violations.under_voltage ?? 0) +
            (result.violations.over_voltage ?? 0) +
            (result.violations.line_overload ?? 0) +
            (result.violations.trafo_overload ?? 0),
        });
      } catch (err) {
        updateRun(tempRunId, { status: "failed" });
        const message = err instanceof Error ? err.message : String(err);
        setOpendssRunState({ phase: "error", message });
        toast.error(message);
      }
    });

    createRun({
      scenarioId: pendingScenario.id,
      scenarioName: pendingScenario.name,
      networkName: networks.find((n) => n.id === networkId)?.name,
      runId: tempRunId,
      networkId,
      status: initialStatus,
      createdBy: pendingScenario.createdBy,
    });

    setOpendssRunState({ phase: initialStatus });
    if (initialStatus === "queued") {
      toast.info("Simulation queued — will start when the current run finishes.");
    }
  };

  // ── Power-flow handler (SimBench + OpenDSS) ────────────────────────────────
  const handlePowerFlowRun = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!networkId) { toast.error("Please select a network"); return; }

    const _networkId = networkId;
    const _networks  = networks;
    const dateStr    = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const _pfTime    = pfTime;
    const tempRunId  = `run-pending-${Date.now()}`;
    const createdBy  = getCurrentUserInfo()?.name ?? "unknown";

    const initialStatus = enqueue(async () => {
      updateRun(tempRunId, { status: "running" });
      setSubmitPhase("running");
      try {
        const result = await runPowerFlow(_networkId, dateStr, _pfTime);
        setLastRunId(result.run_id);
        removeRun(tempRunId);
        createRun({
          scenarioId: "",
          scenarioName: `Power flow · ${dateStr} ${_pfTime}`,
          networkName: _networks.find((n) => n.id === _networkId)?.name,
          runId: result.run_id,
          networkId: _networkId,
          startedAtIso: result.started_at,
          durationSeconds: result.duration_seconds,
          violations: result.violations.total,
          createdBy,
        });
        toast.success(`Power flow completed — run ${result.run_id}`);
      } catch (err) {
        updateRun(tempRunId, { status: "failed" });
        toast.error(err instanceof Error ? err.message : "Power flow failed");
      } finally {
        setSubmitPhase("idle");
      }
    });

    // Create a visible placeholder entry immediately (same pattern as handleRun)
    createRun({
      scenarioId: "",
      scenarioName: `Power flow · ${dateStr} ${_pfTime}`,
      networkName: networks.find((n) => n.id === networkId)?.name,
      runId: tempRunId,
      networkId,
      status: initialStatus,
      createdBy,
    });

    setSubmitPhase(initialStatus);
    if (initialStatus === "queued") {
      toast.info("Power flow queued — will start when the current run finishes.");
    }
  };

  const isRunning = simType === "power_flow"
    ? submitPhase === "running"
    : isOpenDSSNetwork
    ? opendssRunState.phase === "running"
    : submitPhase === "running";

  const isQueued = simType === "power_flow"
    ? submitPhase === "queued"
    : isOpenDSSNetwork
    ? opendssRunState.phase === "queued"
    : submitPhase === "queued";

  return (
    <AppShell>
      <PageHeader
        title="Scenario Builder"
        description="Define a simulation scenario and dispatch it to the backend."
      />

      <div className="grid gap-6 lg:grid-cols-3">
        <form
          onSubmit={
            simType === "power_flow"
              ? handlePowerFlowRun
              : isOpenDSSNetwork
              ? handleOpenDSSRun
              : handleRun
          }
          className="lg:col-span-2 space-y-6"
        >
          {/* ── General card (always shown) ──────────────────────────── */}
          <Card className="p-6">
            <div className="flex items-center gap-2 mb-4">
              <Wand2 className="h-4 w-4 text-primary" />
              <div className="text-sm font-semibold">General</div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2 sm:col-span-2">
                <Label htmlFor="name">Scenario name</Label>
                <Input id="name" value={name} onChange={(e) => setName(e.target.value)} required />
              </div>
              <div className="space-y-2 sm:col-span-2">
                <Label>Network</Label>
                <Select
                  value={networkId}
                  onValueChange={(v) => {
                    setNetworkId(v);
                    setOpendssRunState({ phase: "idle" });
                  }}
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {networks.map((n) => (
                      <SelectItem key={n.id} value={n.id}>
                        {n.name} <span className="text-muted-foreground ml-1">· {n.voltage}</span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </Card>

          {isOpenDSSNetwork ? (
            /* ── OpenDSS: mirrors SimBench Simulation + Horizon cards ─── */
            <>
              {/* Simulation card */}
              <Card className="p-6">
                <div className="flex items-center gap-2 mb-4">
                  <Layers className="h-4 w-4 text-primary" />
                  <div className="text-sm font-semibold">Simulation</div>
                </div>
                <div className="grid gap-6 sm:grid-cols-2">
                  {/* Simulation type toggle */}
                  <div className="space-y-2">
                    <Label>Simulation type</Label>
                    <RadioGroup
                      value={simType}
                      onValueChange={(v) => setSimType(v as SimType)}
                      className="grid gap-2"
                    >
                      {([
                        { value: "time_series", label: "Time-series",  desc: "Single-day profile driven sweep" },
                        { value: "power_flow",  label: "Power flow",   desc: "Single-timestep snapshot" },
                      ] as const).map((opt) => (
                        <Label
                          key={opt.value}
                          className={
                            "flex items-start gap-3 rounded-md border p-3 cursor-pointer transition-colors " +
                            (simType === opt.value
                              ? "border-primary bg-primary/5"
                              : "border-border hover:bg-muted/40")
                          }
                        >
                          <RadioGroupItem value={opt.value} className="hidden" />
                          <div>
                            <div className="font-medium text-sm">{opt.label}</div>
                            <div className="text-xs text-muted-foreground">{opt.desc}</div>
                          </div>
                        </Label>
                      ))}
                    </RadioGroup>
                  </div>

                  {/* Mode (locked — determined by network) */}
                  <div className="space-y-2">
                    <Label>Mode</Label>
                    <div className="rounded-md border border-primary bg-primary/5 p-3">
                      <div className="font-medium text-sm capitalize">{opendssMode ?? "—"}</div>
                      <div className="text-xs text-muted-foreground">
                        {opendssMode === "unbalanced"
                          ? "Asymmetric three-phase"
                          : "Symmetric three-phase"}
                      </div>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Mode is determined by the selected network.
                    </p>
                  </div>
                </div>
              </Card>

              {simType === "time_series" ? (
                /* Simulation horizon card */
                <Card className="p-6">
                  <div className="flex items-center gap-2 mb-1">
                    <CalendarClock className="h-4 w-4 text-primary" />
                    <div className="text-sm font-semibold">Simulation horizon</div>
                  </div>
                  <p className="text-xs text-muted-foreground mb-4">
                    Simulation of a full day in 48 half-hour steps.
                  </p>

                  {/* Horizon selector — Day locked, Week/Month unavailable */}
                  <div className="grid gap-2 sm:grid-cols-3 mb-6">
                    {([
                      { value: "day",   label: "Day",   desc: "48-step · 30 min" },
                      { value: "week",  label: "Week",  desc: "Not available" },
                      { value: "month", label: "Month", desc: "Not available" },
                    ] as const).map((opt) => (
                      <div
                        key={opt.value}
                        className={cn(
                          "flex items-start gap-3 rounded-md border p-3 transition-colors",
                          opt.value === "day"
                            ? "border-primary bg-primary/5"
                            : "border-border opacity-40",
                        )}
                      >
                        <div>
                          <div className="font-medium text-sm">{opt.label}</div>
                          <div className="text-xs text-muted-foreground">{opt.desc}</div>
                        </div>
                      </div>
                    ))}
                  </div>

                  <div className="grid gap-4 sm:grid-cols-3">
                    <div className="space-y-2">
                      <Label htmlFor="opendss-year">Year</Label>
                      <Input
                        id="opendss-year"
                        type="number"
                        min={2000}
                        max={2100}
                        value={year}
                        onChange={(e) => setYear(Number(e.target.value) || 2014)}
                        disabled
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Month</Label>
                      <Select
                        value={month}
                        onValueChange={(v) => {
                          setMonth(v);
                          const maxDay = new Date(year, Number(v), 0).getDate();
                          if (Number(day) > maxDay) setDay(String(maxDay));
                        }}
                        disabled={isRunning}
                      >
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {MONTHS.map((m, i) => (
                            <SelectItem key={m} value={String(i + 1)}>{m}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label>Day</Label>
                      <Select value={day} onValueChange={setDay} disabled={isRunning}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {Array.from(
                            { length: new Date(year, Number(month), 0).getDate() },
                            (_, i) => i + 1,
                          ).map((d) => (
                            <SelectItem key={d} value={String(d)}>{d}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                </Card>
              ) : (
                /* Power flow: Date & Time card */
                <PowerFlowDateTimeCard
                  year={year} month={month} day={day}
                  pfTime={pfTime} isRunning={isRunning}
                  setMonth={setMonth} setDay={setDay} setPfTime={setPfTime}
                />
              )}
            </>
          ) : (
            /* ── Standard SimBench: Simulation + Horizon cards ────────── */
            <>
              <Card className="p-6">
                <div className="flex items-center gap-2 mb-4">
                  <Layers className="h-4 w-4 text-primary" />
                  <div className="text-sm font-semibold">Simulation</div>
                </div>
                <div className="grid gap-6 sm:grid-cols-2">
                  {/* Simulation type toggle */}
                  <div className="space-y-2">
                    <Label>Simulation type</Label>
                    <RadioGroup
                      value={simType}
                      onValueChange={(v) => setSimType(v as SimType)}
                      className="grid gap-2"
                    >
                      {([
                        { value: "time_series", label: "Time-series", desc: "Profile-driven sweep" },
                        { value: "power_flow",  label: "Power flow",  desc: "Single-timestep snapshot" },
                      ] as const).map((opt) => (
                        <Label
                          key={opt.value}
                          className={
                            "flex items-start gap-3 rounded-md border p-3 cursor-pointer transition-colors " +
                            (simType === opt.value
                              ? "border-primary bg-primary/5"
                              : "border-border hover:bg-muted/40")
                          }
                        >
                          <RadioGroupItem value={opt.value} className="hidden" />
                          <div>
                            <div className="font-medium text-sm">{opt.label}</div>
                            <div className="text-xs text-muted-foreground">{opt.desc}</div>
                          </div>
                        </Label>
                      ))}
                    </RadioGroup>
                  </div>

                  <div className="space-y-2">
                    <Label>Mode</Label>
                    <RadioGroup
                      value={mode}
                      onValueChange={(v) => setMode(v as Mode)}
                      className="grid gap-2"
                    >
                      <Label
                        className={
                          "flex items-start gap-3 rounded-md border p-3 cursor-pointer transition-colors " +
                          (mode === "balanced" ? "border-primary bg-primary/5" : "border-border hover:bg-muted/40")
                        }
                      >
                        <RadioGroupItem value="balanced" className="hidden" />
                        <div>
                          <div className="font-medium text-sm">Balanced</div>
                          <div className="text-xs text-muted-foreground">Symmetric three-phase</div>
                        </div>
                      </Label>
                    </RadioGroup>
                    <p className="text-xs text-muted-foreground">
                      SimBench networks support balanced simulation.
                    </p>
                  </div>
                </div>
              </Card>

              {simType === "time_series" ? (
                /* Simulation horizon card */
                <Card className="p-6">
                  <div className="flex items-center gap-2 mb-1">
                    <CalendarClock className="h-4 w-4 text-primary" />
                    <div className="text-sm font-semibold">Simulation horizon</div>
                  </div>
                  <p className="text-xs text-muted-foreground mb-4">
                    Choose the time window the simulation should cover.
                  </p>

                  <RadioGroup
                    value={horizon}
                    onValueChange={(v) => setHorizon(v as Horizon)}
                    className="grid gap-2 sm:grid-cols-3 mb-6"
                  >
                    {([
                      { value: "day",   label: "Day",   desc: "24 h sweep" },
                      { value: "week",  label: "Week",  desc: "7-day window" },
                      { value: "month", label: "Month", desc: "Full month" },
                    ] as const).map((opt) => (
                      <Label
                        key={opt.value}
                        className={
                          "flex items-start gap-3 rounded-md border p-3 cursor-pointer transition-colors " +
                          (horizon === opt.value
                            ? "border-primary bg-primary/5"
                            : "border-border hover:bg-muted/40")
                        }
                      >
                        <RadioGroupItem value={opt.value} className="mt-1" />
                        <div>
                          <div className="font-medium text-sm">{opt.label}</div>
                          <div className="text-xs text-muted-foreground">{opt.desc}</div>
                        </div>
                      </Label>
                    ))}
                  </RadioGroup>

                  <p className="text-xs text-muted-foreground mb-4">
                    Simulations are based on SimBench profiles.
                  </p>

                  <div className="grid gap-4 sm:grid-cols-3">
                    <div className="space-y-2">
                      <Label htmlFor="year">Year</Label>
                      <Input
                        id="year"
                        type="number"
                        min={2000}
                        max={2100}
                        value={year}
                        onChange={(e) => setYear(Number(e.target.value) || 2016)}
                        disabled
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Month</Label>
                      <Select value={month} onValueChange={(v) => {
                        setMonth(v);
                        const maxDay = new Date(year, Number(v), 0).getDate();
                        if (Number(day) > maxDay) setDay(String(maxDay));
                      }}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {MONTHS.map((m, i) => (
                            <SelectItem key={m} value={String(i + 1)}>{m}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    {horizon !== "month" && (
                      <div className="space-y-2">
                        <Label>{horizon === "week" ? "Start day" : "Day"}</Label>
                        <Select value={day} onValueChange={setDay}>
                          <SelectTrigger><SelectValue /></SelectTrigger>
                          <SelectContent>
                            {Array.from(
                              { length: new Date(year, Number(month), 0).getDate() },
                              (_, i) => i + 1,
                            ).map((d) => (
                              <SelectItem key={d} value={String(d)}>{d}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    )}
                  </div>
                </Card>
              ) : (
                /* Power flow: Date & Time card */
                <PowerFlowDateTimeCard
                  year={year} month={month} day={day}
                  pfTime={pfTime} isRunning={isRunning}
                  setMonth={setMonth} setDay={setDay} setPfTime={setPfTime}
                />
              )}
            </>
          )}

          {/* ── Error banner (inline, above Run button) ───────────────── */}
          {isOpenDSSNetwork && opendssRunState.phase === "error" && (
            <div className="flex items-start gap-2 p-3 rounded-lg border border-destructive/30 bg-destructive/5">
              <AlertCircle className="h-4 w-4 text-destructive mt-0.5 shrink-0" />
              <p className="text-xs text-muted-foreground font-mono whitespace-pre-wrap break-all">
                {opendssRunState.message}
              </p>
            </div>
          )}

          <div className="flex items-center justify-end gap-2">
            <Button
              type="submit"
              disabled={isRunning || isQueued}
              variant={isQueued ? "outline" : "default"}
            >
              {isRunning ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Running simulation…
                </>
              ) : isQueued ? (
                <>
                  <Clock className="h-4 w-4 mr-2 animate-pulse" />
                  Queued
                </>
              ) : (
                <>
                  <Play className="h-4 w-4 mr-2" />
                  Run Simulation
                </>
              )}
            </Button>
          </div>
        </form>

        {/* ── Sidebar ─────────────────────────────────────────────────── */}
        <div className="space-y-4">
          {/* Summary card */}
          <Card className="p-5">
            <div className="text-sm font-semibold mb-3">Summary</div>
            <dl className="space-y-2 text-sm">
              <Row k="Name" v={name} />
              <Row k="Network" v={networks.find((n) => n.id === networkId)?.name ?? "—"} />
              {simType === "power_flow" ? (
                <>
                  <Row k="Type" v="power flow" />
                  <Row k="Date" v={`${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`} />
                  <Row k="Time" v={pfTime} />
                  {lastRunId && <Row k="Run ID" v={lastRunId} />}
                </>
              ) : isOpenDSSNetwork ? (
                <>
                  <Row k="Type" v="time-series" />
                  <Row k="Mode" v={opendssMode ?? "—"} />
                  <Row k="Horizon" v="day" />
                  <Row k="Date" v={`${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`} />
                  {opendssRunState.phase === "done" && (
                    <Row k="Run ID" v={opendssRunState.result.run_id} />
                  )}
                </>
              ) : (
                <>
                  <Row k="Type" v="time-series" />
                  <Row k="Mode" v={mode} />
                  <Row k="Horizon" v={horizon} />
                  {horizon === "month" ? (
                    <Row k="Date" v={`${year}-${String(month).padStart(2, "0")}`} />
                  ) : (
                    <Row
                      k={horizon === "week" ? "Start date" : "Date"}
                      v={`${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`}
                    />
                  )}
                  {lastRunId && <Row k="Run ID" v={lastRunId} />}
                </>
              )}
            </dl>
          </Card>

          {/* Recent scenarios (always shown) */}
          <Card className="p-5">
            <div className="text-sm font-semibold mb-3">Recent scenarios</div>
            <div className="space-y-2 text-sm">
              {scenarios.slice(0, 6).map((s) => (
                <div
                  key={s.id}
                  className="flex items-center justify-between gap-2 py-1.5 border-b border-border/60 last:border-0"
                >
                  <div className="min-w-0">
                    <div className="font-medium truncate">{s.name}</div>
                    <div className="text-xs text-muted-foreground">
                      {s.simType.replace("_", " ")} · {s.createdBy} · {s.createdAt}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </AppShell>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <dt className="text-muted-foreground">{k}</dt>
      <dd className="font-medium text-right capitalize">{v}</dd>
    </div>
  );
}

/** Shared Date & Time card for power-flow mode (SimBench + OpenDSS). */
function PowerFlowDateTimeCard({
  year, month, day, pfTime, isRunning,
  setMonth, setDay, setPfTime,
}: {
  year: number; month: string; day: string; pfTime: string; isRunning: boolean;
  setMonth: (v: string) => void; setDay: (v: string) => void; setPfTime: (v: string) => void;
}) {
  // Generate 96 time options at 15-min intervals (00:00 … 23:45)
  const timeOptions = Array.from({ length: 96 }, (_, i) => {
    const h = Math.floor(i / 4).toString().padStart(2, "0");
    const m = ((i % 4) * 15).toString().padStart(2, "0");
    return `${h}:${m}`;
  });

  return (
    <Card className="p-6">
      <div className="flex items-center gap-2 mb-1">
        <CalendarClock className="h-4 w-4 text-primary" />
        <div className="text-sm font-semibold">Date &amp; Time</div>
      </div>
      <p className="text-xs text-muted-foreground mb-4">
        Run a single power-flow snapshot at the chosen date and time (15-min resolution).
      </p>
      <div className="grid gap-4 sm:grid-cols-4">
        <div className="space-y-2">
          <Label>Year</Label>
          <Input type="number" value={year} disabled />
        </div>
        <div className="space-y-2">
          <Label>Month</Label>
          <Select
            value={month}
            onValueChange={(v) => {
              setMonth(v);
              const maxDay = new Date(year, Number(v), 0).getDate();
              if (Number(day) > maxDay) setDay(String(maxDay));
            }}
            disabled={isRunning}
          >
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {MONTHS.map((m, i) => (
                <SelectItem key={m} value={String(i + 1)}>{m}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label>Day</Label>
          <Select value={day} onValueChange={setDay} disabled={isRunning}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {Array.from(
                { length: new Date(year, Number(month), 0).getDate() },
                (_, i) => i + 1,
              ).map((d) => (
                <SelectItem key={d} value={String(d)}>{d}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label>Time</Label>
          <Select value={pfTime} onValueChange={setPfTime} disabled={isRunning}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {timeOptions.map((t) => (
                <SelectItem key={t} value={t}>{t}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
    </Card>
  );
}
