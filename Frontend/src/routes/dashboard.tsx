import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { AppShell, PageHeader, StatusBadge } from "@/components/app-shell";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useRuns } from "@/lib/runs-store";
import { useScenarios } from "@/lib/scenarios-store";
import { useNetworks, seedNetworks } from "@/lib/networks-store";
import { useConversions } from "@/lib/conversions-store";
import { fetchSimbenchNetworks } from "@/lib/api";
import {
  computeSystemOverview,
  type SystemViolationOverview,
} from "@/lib/violations-overview";
import {
  Activity,
  Network as NetIcon,
  AlertTriangle,
  PlayCircle,
  Plus,
  Upload,
  FlaskConical,
  ChartSpline,
  CheckCircle2,
  XCircle,
  ArrowRight,
  ChevronRight,
  Zap,
  TrendingUp,
  Wrench,
  Users as UsersIcon,
  LayoutGrid,
} from "lucide-react";
import { useRole } from "@/hooks/use-role";

export const Route = createFileRoute("/dashboard")({
  head: () => ({
    meta: [
      { title: "Dashboard — DT Lab" },
      { name: "description", content: "Operational overview of networks, runs and violations." },
    ],
  }),
  component: Dashboard,
});

/**
 * A thin progress bar that animates from 0 → target on mount, and smoothly
 * transitions whenever the value changes afterward.
 * `delay` staggers the entrance animation for cascade effects (ms).
 */
function AnimatedBar({
  pct,
  barClass = "bg-primary",
  delay = 0,
}: {
  pct: number;
  barClass?: string;
  delay?: number;
}) {
  const [width, setWidth] = useState(0);
  const isFirst = useRef(true);

  useEffect(() => {
    if (isFirst.current) {
      isFirst.current = false;
      const t = setTimeout(() => setWidth(pct), delay);
      return () => clearTimeout(t);
    }
    // Subsequent data changes animate via the CSS transition directly.
    setWidth(pct);
  }, [pct, delay]);

  return (
    <div className="h-1.5 rounded-full bg-muted overflow-hidden">
      <div
        className={"h-full rounded-full " + barClass}
        style={{ width: `${width}%`, transition: "width 0.85s cubic-bezier(0.4, 0, 0.2, 1)" }}
      />
    </div>
  );
}

function Dashboard() {
  // Fetch networks client-side so the Bearer token (stored in localStorage)
  // is always available.  The route loader was removed because it runs on the
  // server during SSR where localStorage — and therefore the auth token — is
  // not accessible, which caused networks to always be empty on page refresh.
  useEffect(() => {
    fetchSimbenchNetworks().then(({ networks }) => {
      if (networks.length > 0) seedNetworks(networks);
    }).catch(() => {});
  }, []);

  const networks = useNetworks();
  const runs = useRuns();
  const scenarios = useScenarios();
  const conversions = useConversions();

  const stats = useMemo(() => {
    const active = runs.filter((r) => r.status === "running" || r.status === "queued").length;
    const failed = runs.filter((r) => r.status === "failed").length;
    const completed = runs.filter((r) => r.status === "completed");
    const lastSuccess = completed[0]?.startedAt ?? "—";
    // Tally total violations from completed run metadata
    const openViolations = completed.reduce(
      (sum, r) => sum + ((r as typeof r & { violations?: number }).violations ?? 0),
      0,
    );
    return {
      networks: networks.length,
      completedRuns: completed.length,
      active,
      openViolations,
      failed,
      lastSuccess,
    };
  }, [runs, networks]);

  const [systemOverview, setSystemOverview] =
    useState<SystemViolationOverview | null>(null);
  const [systemLoading, setSystemLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (networks.length === 0) {
      setSystemOverview(null);
      return;
    }
    // Reset immediately so the loading state is visible while we re-fetch.
    setSystemOverview(null);
    setSystemLoading(true);
    // Only pass runs whose network still exists — deleted networks leave their
    // result files on disk, so without this filter their violations would
    // continue to appear even after the network record is removed.
    const existingNetworkIds = new Set(networks.map((n) => n.id));
    const activeRuns = runs
      .map((r) => ({
        id: r.id,
        networkId: (r as { networkId?: string }).networkId,
        status: r.status,
      }))
      .filter((r) => r.networkId && existingNetworkIds.has(r.networkId));
    computeSystemOverview(activeRuns, networks.length)
      .then((res) => {
        if (!cancelled) setSystemOverview(res);
      })
      .catch(() => {
        if (!cancelled) setSystemOverview(null);
      })
      .finally(() => {
        if (!cancelled) setSystemLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [runs, networks]);

  const networkOverview = useMemo(() => {
    return networks
      .map((n) => {
        const netRuns = runs.filter(
          (r) => (r as typeof r & { networkId?: string }).networkId === n.id,
        );
        const last = netRuns[0];
        return {
          id: n.id,
          name: n.name,
          lastStatus: (last?.status ?? "—") as string,
          runCount: netRuns.length,
        };
      })
      .sort((a, b) => b.runCount - a.runCount)
      .slice(0, 7);
  }, [runs, networks]);

  const activity = useMemo(() => {
    type ActivityItem = { icon: typeof PlayCircle; tone: string; text: string; time: string; user: string; sortKey: string };
    const items: ActivityItem[] = [];

    const userForRun = (r: { scenarioId: string; scenarioName: string; createdBy?: string }) => {
      if (r.createdBy) return r.createdBy;
      const scn =
        (r.scenarioId ? scenarios.find((s) => s.id === r.scenarioId) : null) ??
        scenarios.find((s) => s.name === r.scenarioName);
      return scn?.createdBy ?? "—";
    };

    // Simulation run events — treat missing timestamps as oldest so they sink to bottom
    runs.forEach((r) => {
      const user = userForRun(r);
      const sortKey = r.startedAt === "—" ? "0000-00-00 00:00" : r.startedAt;
      if (r.status === "completed") {
        items.push({ icon: CheckCircle2, tone: "text-success", text: `Run ${r.id} completed — ${r.scenarioName}`, time: r.startedAt, user, sortKey });
      } else if (r.status === "running") {
        items.push({ icon: PlayCircle, tone: "text-info", text: `Run ${r.id} started — ${r.scenarioName}`, time: r.startedAt, user, sortKey });
      } else if (r.status === "failed") {
        items.push({ icon: XCircle, tone: "text-destructive", text: `Run ${r.id} failed — ${r.scenarioName}`, time: r.startedAt, user, sortKey });
      }
    });

    // Highlight the most recent run that had violations
    const violatingRun = runs
      .filter((r) => r.status === "completed" && ((r as typeof r & { violations?: number }).violations ?? 0) > 0)
      .at(0);
    if (violatingRun) {
      const sortKey = violatingRun.startedAt === "—" ? "0000-00-00 00:00" : violatingRun.startedAt;
      items.push({
        icon: AlertTriangle,
        tone: "text-warning-foreground",
        text: `Violations detected on run ${violatingRun.id} (${(violatingRun as typeof violatingRun & { violations?: number }).violations} total)`,
        time: violatingRun.startedAt,
        user: userForRun(violatingRun),
        sortKey,
      });
    }

    // Network conversion / validation events — sourced from the conversions store.
    conversions.forEach((c) => {
      const isValidation = c.type === "validation";
      items.push({
        icon: isValidation ? CheckCircle2 : Wrench,
        tone: isValidation ? "text-success" : "text-primary",
        text: isValidation
          ? `Network validated — ${c.networkName}`
          : `Network converted — ${c.networkName}`,
        time: c.convertedAt,
        user: c.convertedBy,
        sortKey: c.convertedAt,
      });
    });

    // Sort newest first, deduplicate by text, cap at 6
    items.sort((a, b) => b.sortKey.localeCompare(a.sortKey));
    const seen = new Set<string>();
    return items.filter((a) => {
      if (seen.has(a.text)) return false;
      seen.add(a.text);
      return true;
    }).slice(0, 6);
  }, [runs, scenarios, conversions]);

  type SummaryCard = {
    label: string;
    value: string | number;
    sub?: string;
    icon: typeof NetIcon;
    accent: "neutral" | "primary" | "info" | "warning" | "destructive" | "success";
    to: "/networks" | "/scenarios" | "/runs" | "/results";
    isText?: boolean;
  };

  const completedCount = runs.filter((r) => r.status === "completed").length;
  const runningCount = runs.filter((r) => r.status === "running").length;
  const queuedCount = runs.filter((r) => r.status === "queued").length;
  const summary: SummaryCard[] = [
    { label: "Networks", value: stats.networks, sub: `${networks.filter((n) => n.status === "validated").length} validated`, icon: NetIcon, accent: "neutral", to: "/networks" },
    { label: "Completed Runs", value: stats.completedRuns, sub: "view results", icon: FlaskConical, accent: "neutral", to: "/runs" },
    { label: "Active Runs", value: stats.active, sub: `${runningCount} running · ${queuedCount} queued`, icon: PlayCircle, accent: "info", to: "/runs" },
    
    { label: "Failed Runs", value: stats.failed, sub: stats.failed > 0 ? "needs attention" : "all healthy", icon: XCircle, accent: "destructive", to: "/runs" },
    { label: "Last Successful Run", value: stats.lastSuccess, sub: `${completedCount} completed total`, icon: CheckCircle2, accent: "success", to: "/runs", isText: true },
  ];

  const accentStyles: Record<SummaryCard["accent"], { ring: string; iconBg: string; iconColor: string; strip: string; valueColor: string }> = {
    neutral: { ring: "hover:border-border", iconBg: "bg-muted", iconColor: "text-foreground/70", strip: "bg-border", valueColor: "text-foreground" },
    primary: { ring: "hover:border-primary/40", iconBg: "bg-primary/10", iconColor: "text-primary", strip: "bg-primary", valueColor: "text-foreground" },
    info: { ring: "hover:border-info/40", iconBg: "bg-info/10", iconColor: "text-info", strip: "bg-info", valueColor: "text-foreground" },
    warning: { ring: "hover:border-warning/50", iconBg: "bg-warning/15", iconColor: "text-warning-foreground", strip: "bg-warning", valueColor: "text-warning-foreground" },
    destructive: { ring: "hover:border-destructive/40", iconBg: "bg-destructive/10", iconColor: "text-destructive", strip: "bg-destructive", valueColor: "text-destructive" },
    success: { ring: "hover:border-success/40", iconBg: "bg-success/10", iconColor: "text-success", strip: "bg-success", valueColor: "text-foreground" },
  };

  const { role } = useRole();

  const allActions = [
    { key: "upload", label: "Inspect Networks", icon: NetIcon, to: "/networks" as const },
    { key: "scenario", label: "Create Scenario", icon: FlaskConical, to: "/scenarios" as const },
    { key: "run", label: "Start New Run", icon: PlayCircle, to: "/scenarios" as const },
    { key: "results", label: "Analytics", icon: ChartSpline, to: "/results" as const },
    { key: "violations", label: "Run Violation Detection", icon: AlertTriangle, to: "/results" as const },
    { key: "conversion", label: "Conversion Tools", icon: Wrench, to: "/conversion-tools" as const },
    { key: "users", label: "Manage Users", icon: UsersIcon, to: "/users" as const },
    { key: "library", label: "Open Network Library", icon: NetIcon, to: "/networks" as const },
    { key: "dashboard", label: "Open Dashboard", icon: LayoutGrid, to: "/dashboard" as const },
  ];

  const actionsByRole: Record<string, string[]> = {
    admin: ["upload", "scenario", "run", "results", "violations", "conversion", "users"],
    researcher: ["upload", "scenario", "run", "results", "violations", "conversion"],
    student: ["upload", "run", "results", "violations"],
  };

  const allowedKeys = role ? actionsByRole[role] ?? [] : [];
  const quickActions = allowedKeys
    .map((k) => allActions.find((a) => a.key === k))
    .filter((a): a is (typeof allActions)[number] => Boolean(a));

  const recentRuns = runs.slice(0, 6);

  const allowedRoutes: Record<string, Set<string>> = {
    admin: new Set(["/dashboard", "/networks", "/scenarios", "/runs", "/results", "/conversion-tools", "/users"]),
    researcher: new Set(["/dashboard", "/networks", "/scenarios", "/runs", "/results", "/conversion-tools"]),
    student: new Set(["/dashboard", "/networks", "/runs", "/results"]),
  };
  const canAccess = (to: string) => (role ? allowedRoutes[role]?.has(to) ?? false : false);

  return (
    <AppShell>
      <PageHeader
        title="Dashboard"
        description="Operational overview of your Digital Twin workspace."
        actions={
          canAccess("/scenarios") ? (
            <Button asChild>
              <Link to="/scenarios" search={{}}>
                <Plus className="h-4 w-4 mr-2" /> New Run
              </Link>
            </Button>
          ) : null
        }
      />

      {/* 1. Summary cards */}
      <div
        className="grid gap-4 grid-cols-2 md:grid-cols-3 mb-6"
        style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}
      >
        {summary.map((k) => {
          const Icon = k.icon;
          const a = accentStyles[k.accent];
          const allowed = canAccess(k.to);
          const baseClass =
            "group relative overflow-hidden rounded-xl border bg-card text-card-foreground shadow-sm " +
            "transition-all duration-200 hover:shadow-md hover:-translate-y-0.5 " +
            a.ring;
          const inner = (
            <>
              <span className={"absolute inset-y-0 left-0 w-1 " + a.strip} aria-hidden />
              <div className="p-4 pl-5">
                <div className="flex items-start justify-between">
                  <div className={"flex h-10 w-10 items-center justify-center rounded-full " + a.iconBg + " " + a.iconColor + " transition-transform duration-200 group-hover:scale-110"}>
                    <Icon className="h-5 w-5" />
                  </div>
                  {allowed && (
                    <ChevronRight className="h-4 w-4 text-muted-foreground opacity-0 -translate-x-1 transition-all duration-200 group-hover:opacity-100 group-hover:translate-x-0" />
                  )}
                </div>
                <div className="mt-3 text-[11px] uppercase tracking-wider text-muted-foreground font-semibold">
                  {k.label}
                </div>
                <div
                  className={
                    "mt-1 font-semibold tracking-tight tabular-nums " + a.valueColor + " " +
                    (k.isText ? "text-base leading-snug" : "text-3xl")
                  }
                >
                  {k.value}
                </div>
                {k.sub && (
                  <div className="mt-1 text-xs text-muted-foreground truncate">{k.sub}</div>
                )}
              </div>
            </>
          );
          return allowed ? (
            <Link key={k.label} to={k.to} className={baseClass}>
              {inner}
            </Link>
          ) : (
            <div key={k.label} className={baseClass + " cursor-default"} aria-disabled="true">
              {inner}
            </div>
          );
        })}
      </div>

      {/* 2. Quick Actions */}
      <Card className="p-5 mb-6">
        <div className="flex items-center gap-2 mb-4">
          <Zap className="h-4 w-4 text-primary" />
          <div className="text-sm font-semibold">Quick Actions</div>
        </div>
        <div className="flex flex-wrap sm:flex-nowrap gap-2 w-full">
          {quickActions.map((a) => {
            const Icon = a.icon;
            return (
              <Button
                key={a.label}
                asChild
                variant="outline"
                className="h-auto flex-1 min-w-0 basis-0 justify-start py-3 px-3 font-normal"
              >
                <Link to={a.to}>
                  <Icon className="h-4 w-4 mr-2 text-primary shrink-0" />
                  <span className="text-xs truncate">{a.label}</span>
                </Link>
              </Button>
            );
          })}
        </div>
      </Card>

      {/* 3. Recent Runs — main section */}
      <Card className="p-5 mb-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="text-sm font-semibold">Recent Simulation Runs</div>
            <div className="text-xs text-muted-foreground">Latest jobs across all networks</div>
          </div>
          {canAccess("/runs") && (
            <Button variant="ghost" size="sm" asChild>
              <Link to="/runs">
                View all <ChevronRight className="h-4 w-4 ml-1" />
              </Link>
            </Button>
          )}
        </div>
        <div className="overflow-x-auto -mx-5 px-5">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wider text-muted-foreground border-b border-border">
                <th className="py-2 pr-4 font-medium">Run ID</th>
                <th className="py-2 pr-4 font-medium">Scenario</th>
                <th className="py-2 pr-4 font-medium">Network</th>
                <th className="py-2 pr-4 font-medium">Status</th>
                <th className="py-2 pr-4 font-medium">Started</th>
                <th className="py-2 pr-4 font-medium">Duration</th>
                <th className="py-2 pr-4 font-medium text-center">Violations</th>
                <th className="py-2 pr-2 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {recentRuns.map((r) => (
                <tr key={r.id} className="border-b border-border/60 last:border-0 hover:bg-muted/30">
                  <td className="py-3 pr-4 font-mono text-xs">{r.id}</td>
                  <td className="py-3 pr-4 font-medium">{r.scenarioName}</td>
                  <td className="py-3 pr-4 text-muted-foreground">{r.networkName}</td>
                  <td className="py-3 pr-4"><StatusBadge status={r.status} /></td>
                  <td className="py-3 pr-4 text-muted-foreground text-xs">{r.startedAt}</td>
                  <td className="py-3 pr-4 font-mono text-xs">{r.duration}</td>
                  <td className="py-3 pr-4 font-mono text-center">{r.violations}</td>
                  <td className="py-3 pr-2 text-right">
                    <div className="inline-flex gap-1">
                      {r.status === "completed" && canAccess("/results") && (
                        <Button asChild variant="ghost" size="sm" className="h-7 px-2">
                          <Link to="/results" search={{ runId: r.id }}>
                            <ChartSpline className="h-3.5 w-3.5" />
                          </Link>
                        </Button>
                      )}
                      {r.violations > 0 && canAccess("/results") && (
                        <Button asChild variant="ghost" size="sm" className="h-7 px-2">
                          <Link to="/results" search={{ runId: r.id }}>
                            <AlertTriangle className="h-3.5 w-3.5" />
                          </Link>
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* 4 + 5. Violations Overview + Network Overview */}
      <div className="grid gap-4 lg:grid-cols-2 mb-6">
        <Card className="p-5">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="text-sm font-semibold">Violations Overview</div>
              <div className="text-xs text-muted-foreground">System-wide health across all networks</div>
            </div>
            {canAccess("/results") && (
              <Button variant="ghost" size="sm" asChild>
                <Link to="/results">
                  <ArrowRight className="h-4 w-4" />
                </Link>
              </Button>
            )}
          </div>

          {systemOverview === null ? (
            <div className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
              {systemLoading ? "Loading violations from latest runs…" : "No simulation results available yet."}
            </div>
          ) : (
            <>
              {/* Coverage */}
              <div className="mb-4 rounded-md border border-border bg-muted/30 p-3">
                <div className="flex items-center justify-between">
                  <div className="text-[11px] uppercase tracking-wider text-muted-foreground font-medium">
                    Networks with violations
                  </div>
                  <div className="text-xs font-mono tabular-nums text-muted-foreground">
                    {systemOverview.totalNetworks > 0
                      ? ((systemOverview.networksWithViolations / systemOverview.totalNetworks) * 100).toFixed(0)
                      : 0}
                    %
                  </div>
                </div>
                <div className="mt-1 flex items-baseline gap-2">
                  <div className="text-2xl font-semibold tabular-nums">
                    {systemOverview.networksWithViolations}{" "}
                    <span className="text-muted-foreground text-base font-normal">
                      / {systemOverview.totalNetworks}
                    </span>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    ({systemOverview.networksWithResults} with results)
                  </div>
                </div>
                <div className="mt-2">
                  <AnimatedBar
                    pct={systemOverview.totalNetworks > 0
                      ? (systemOverview.networksWithViolations / systemOverview.totalNetworks) * 100
                      : 0}
                    delay={150}
                  />
                </div>
              </div>

              {/* Normalized metrics */}
              <div className="grid grid-cols-2 gap-3 mb-4">
                {[
                  { label: "Under-voltage", pct: systemOverview.underPct, denom: "of buses ever below 0.94 pu", tone: "text-info", bg: "bg-info/10" },
                  { label: "Over-voltage", pct: systemOverview.overPct, denom: "of buses ever above 1.06 pu", tone: "text-warning-foreground", bg: "bg-warning/15" },
                  { label: "Line overload", pct: systemOverview.linePct, denom: "of lines ever above 100%", tone: "text-destructive", bg: "bg-destructive/10" },
                  { label: "Transformer overload", pct: systemOverview.trafoPct, denom: "of trafos ever above 100%", tone: "text-destructive", bg: "bg-destructive/10" },
                ].map((v) => (
                  <div key={v.label} className={"rounded-md p-3 " + v.bg}>
                    <div className="text-[11px] uppercase tracking-wider text-muted-foreground font-medium truncate">{v.label}</div>
                    <div className={"mt-1 text-2xl font-semibold tabular-nums " + v.tone}>
                      {v.pct.toFixed(2)}<span className="text-base font-normal">%</span>
                    </div>
                    <div className="mt-1 text-[11px] text-muted-foreground truncate">{v.denom}</div>
                  </div>
                ))}
              </div>
            </>
          )}
        </Card>

        <Card className="p-5">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="text-sm font-semibold">Network Overview</div>
              <div className="text-xs text-muted-foreground">Per-network status snapshot</div>
            </div>
            <Button variant="ghost" size="sm" asChild>
              <Link to="/networks">
                <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
          </div>
          <div className="overflow-x-auto -mx-5 px-5 text-left">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wider text-muted-foreground border-b border-border">
                  <th className="py-2 pr-4 font-medium">Network</th>
                  <th className="py-2 pr-4 font-medium text-center">Last Run</th>
                  <th className="py-2 pr-4 font-medium text-center">Runs</th>
                </tr>
              </thead>
              <tbody>
                {networkOverview.map((n) => (
                  <tr key={n.id} className="border-b border-border/60 last:border-0">
                    <td className="py-2.5 pr-4 font-medium truncate max-w-[200px]">{n.name}</td>
                    <td className="py-2.5 pr-4 text-center">
                      {n.lastStatus === "—" ? <span className="text-xs text-muted-foreground">—</span> : <StatusBadge status={n.lastStatus} />}
                    </td>
                    <td className="py-2.5 pr-4 font-mono tabular-nums text-center">{n.runCount}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      {/* 6 + 7. Recent Activity + minimal charts area */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="p-5 lg:col-span-2">
          <div className="flex items-center gap-2 mb-4">
            <Activity className="h-4 w-4 text-primary" />
            <div className="text-sm font-semibold">Recent Activity</div>
          </div>
          <ol className="relative border-l border-border ml-2 space-y-4">
            {activity.map((a, i) => {
              const Icon = a.icon;
              return (
                <li key={i} className="ml-5">
                  <div className={"absolute -left-[11px] flex h-5 w-5 items-center justify-center rounded-full bg-card border border-border " + a.tone}>
                    <Icon className="h-3 w-3" />
                  </div>
                  <div className="flex items-start justify-between gap-3">
                    <div className="text-sm">{a.text}</div>
                    <div className="text-xs text-muted-foreground whitespace-nowrap shrink-0 flex items-center gap-1.5">
                      <span className="font-medium text-foreground/80">{a.user}</span>
                      <span aria-hidden>·</span>
                      <span>{a.time}</span>
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
        </Card>

        <Card className="p-5">
          <div className="flex items-center gap-2 mb-4">
            <TrendingUp className="h-4 w-4 text-primary" />
            <div className="text-sm font-semibold">Runs by Status</div>
          </div>
          <div className="space-y-3">
            {(["completed", "running", "queued", "failed"] as const).map((s, i) => {
              const count = runs.filter((r) => r.status === s).length;
              const pct = runs.length > 0 ? (count / runs.length) * 100 : 0;
              const barClass =
                s === "completed" ? "bg-success" :
                s === "running" ? "bg-info" :
                s === "failed" ? "bg-destructive" : "bg-muted-foreground/40";
              return (
                <div key={s}>
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="capitalize text-muted-foreground">{s}</span>
                    <span className="font-mono tabular-nums">{count}</span>
                  </div>
                  <AnimatedBar pct={pct} barClass={barClass} delay={i * 120} />
                </div>
              );
            })}
          </div>
        </Card>
      </div>
    </AppShell>
  );
}
