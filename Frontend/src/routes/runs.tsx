import { createFileRoute, Link } from "@tanstack/react-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { seedNetworks } from "@/lib/networks-store";
import { fetchSimbenchNetworks } from "@/lib/api";
import { AppShell, PageHeader, StatusBadge } from "@/components/app-shell";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Progress } from "@/components/ui/progress";
import { useRuns, deleteRun, seedRunsFromBackend } from "@/lib/runs-store";
import { useRole } from "@/hooks/use-role";
import { Search, RefreshCw, BarChart3, Trash2 } from "lucide-react";

/**
 * Module-level cache so fake progress survives route navigation.
 * Key = run id, value = last displayed percentage.
 * Cleared when a run reaches "completed" or "failed".
 */
const fakeProgressCache = new Map<string, number>();

/**
 * Progress bar that animates while a run is in the "running" state.
 *
 * Strategy:
 *  - "queued"    → shows 0 %
 *  - "running"   → exponentially approaches 87 %, resuming from the
 *                  cached value so navigating away and back doesn't reset it
 *  - "completed" → snaps to 100 % via the shadcn Progress transition
 *  - "failed"    → shows 0 %
 */
function AnimatedProgress({ runId, progress, status }: { runId: string; progress: number; status: string }) {
  const [displayed, setDisplayed] = useState(() => {
    if (status === "completed") return 100;
    if (status === "running") return fakeProgressCache.get(runId) ?? 0;
    return progress;
  });

  useEffect(() => {
    if (status === "completed" || status === "failed") {
      fakeProgressCache.delete(runId);
      setDisplayed(status === "completed" ? 100 : 0);
      return;
    }
    if (status !== "running") {
      setDisplayed(progress);
      return;
    }
    // Resume from cached value so navigation doesn't restart the animation.
    let current = fakeProgressCache.get(runId) ?? 0;
    const id = setInterval(() => {
      current += (87 - current) * 0.04;
      fakeProgressCache.set(runId, current);
      setDisplayed(current);
    }, 250);
    return () => clearInterval(id);
  }, [runId, status, progress]);

  return (
    <div className="flex items-center gap-2">
      <Progress value={displayed} className="h-1.5" />
      <span className="text-xs text-muted-foreground tabular-nums w-9 text-right">
        {Math.min(100, Math.round(displayed))}%
      </span>
    </div>
  );
}

export const Route = createFileRoute("/runs")({
  validateSearch: (search: Record<string, unknown>): { highlight?: string } => ({
    highlight: typeof search.highlight === "string" ? search.highlight : undefined,
  }),
  head: () => ({
    meta: [
      { title: "Simulation Runs — DT Lab" },
      { name: "description", content: "Track queued, running, completed and failed simulation jobs." },
    ],
  }),
  component: SimulationRuns,
});

function SimulationRuns() {
  const runs = useRuns();
  const { role } = useRole();
  const isAdmin = role === "admin";
  const { highlight } = Route.useSearch();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("all");
  const highlightedRowRef = useRef<HTMLTableRowElement | null>(null);
  const [flashRunId, setFlashRunId] = useState<string | undefined>(highlight);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  // Fetch networks + runs client-side so the Bearer token (localStorage) is
  // always available. The route loader was removed because it runs on the
  // server during SSR where localStorage is not accessible.
  const loadData = useCallback(async () => {
    setRefreshing(true);
    try {
      const { networks: nets } = await fetchSimbenchNetworks();
      if (nets.length > 0) seedNetworks(nets);
      await seedRunsFromBackend();
    } catch {
      // silent — store already has whatever was loaded before
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const handleDelete = async (id: string) => {
    setDeleting(id);
    try {
      await deleteRun(id);
    } catch (e) {
      console.error("Delete failed", e);
    } finally {
      setDeleting(null);
      setConfirmId(null);
    }
  };

  // Scroll & flash the highlighted run when it appears
  useEffect(() => {
    if (!highlight) return;
    setFlashRunId(highlight);
    const t1 = setTimeout(() => {
      highlightedRowRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 50);
    const t2 = setTimeout(() => setFlashRunId(undefined), 4000);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, [highlight]);

  const filtered = runs.filter(
    (r) =>
      (status === "all" || r.status === status) &&
      (q === "" || r.scenarioName.toLowerCase().includes(q.toLowerCase()) || r.id.includes(q)),
  );

  return (
    <AppShell>
      <PageHeader
        title="Simulation Runs"
        description="Monitor the simulation queue and inspect completed jobs."
        actions={
          <Button variant="outline" onClick={loadData} disabled={refreshing}>
            <RefreshCw className={"h-4 w-4 mr-2" + (refreshing ? " animate-spin" : "")} /> Refresh
          </Button>
        }
      />

      <div className="grid gap-4 grid-cols-2 lg:grid-cols-4 mb-6">
        {(["queued", "running", "completed", "failed"] as const).map((s) => {
          const n = runs.filter((r) => r.status === s).length;
          return (
            <Card key={s} className="p-5">
              <div className="text-xs uppercase tracking-wider text-muted-foreground font-medium capitalize">
                {s}
              </div>
              <div className="mt-2 text-3xl font-semibold">{n}</div>
              <div className="mt-2"><StatusBadge status={s} /></div>
            </Card>
          );
        })}
      </div>

      <Card className="p-4 mb-6">
        <div className="flex flex-col md:flex-row gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input placeholder="Search runs by scenario or ID…" value={q} onChange={(e) => setQ(e.target.value)} className="pl-9" />
          </div>
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="w-full md:w-44"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="queued">Queued</SelectItem>
              <SelectItem value="running">Running</SelectItem>
              <SelectItem value="completed">Completed</SelectItem>
              <SelectItem value="failed">Failed</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </Card>

      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted/40">
              <tr className="text-left text-xs uppercase tracking-wider text-muted-foreground">
                <th className="py-3 px-4 font-medium">Run ID</th>
                <th className="py-3 px-4 font-medium">Scenario</th>
                <th className="py-3 px-4 font-medium">Network</th>
                <th className="py-3 px-4 font-medium">Status</th>
                <th className="py-3 px-4 font-medium">Progress</th>
                <th className="py-3 px-4 font-medium">Started</th>
                <th className="py-3 px-4 font-medium">Duration</th>
                <th className="py-3 px-4 font-medium text-center">Violations</th>
                <th className="py-3 px-4 text-center" />
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => {
                const isFlash = r.id === flashRunId;
                return (
                <tr
                  key={r.id}
                  ref={isFlash ? highlightedRowRef : undefined}
                  className={
                    "border-t border-border transition-colors " +
                    (isFlash ? "bg-primary/10 animate-pulse" : "hover:bg-muted/30")
                  }
                >
                  <td className="py-3 px-4 font-mono text-xs">{r.id}</td>
                  <td className="py-3 px-4 font-medium">{r.scenarioName}</td>
                  <td className="py-3 px-4 text-muted-foreground">{r.networkName}</td>
                  <td className="py-3 px-4"><StatusBadge status={r.status} /></td>
                  <td className="py-3 px-4 w-44">
                    <AnimatedProgress runId={r.id} progress={r.progress} status={r.status} />
                  </td>
                  <td className="py-3 px-4 text-muted-foreground text-xs">{r.startedAt}</td>
                  <td className="py-3 px-4 font-mono text-xs">{r.duration}</td>
                  <td className="py-3 px-4 font-mono text-center">
                    {r.violations > 0 ? (
                      <Link
                        to="/results"
                        search={{
                          runId: r.id,
                          networkId: (r as typeof r & { networkId?: string }).networkId,
                        }}
                        className="text-primary hover:underline"
                      >
                        {r.violations}
                      </Link>
                    ) : (
                      r.violations
                    )}
                  </td>
                  <td className="py-3 px-4 text-center">
                    <div className="flex items-center justify-center gap-1">
                      {r.status === "completed" && (
                        <Button asChild variant="ghost" size="sm">
                          <Link
                            to="/results"
                            search={{
                              runId: r.id,
                              networkId: (r as typeof r & { networkId?: string }).networkId,
                            }}
                          >
                            <BarChart3 className="h-4 w-4 mr-1" /> Results
                          </Link>
                        </Button>
                      )}
                      {isAdmin && (confirmId === r.id ? (
                        <>
                          <Button
                            variant="destructive"
                            size="sm"
                            disabled={deleting === r.id}
                            onClick={() => handleDelete(r.id)}
                            className="h-7 px-2 text-xs"
                          >
                            {deleting === r.id ? "Deleting…" : "Confirm"}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setConfirmId(null)}
                            className="h-7 px-2 text-xs"
                          >
                            Cancel
                          </Button>
                        </>
                      ) : (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setConfirmId(r.id)}
                          className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                          title="Delete run"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      ))}
                    </div>
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </AppShell>
  );
}
