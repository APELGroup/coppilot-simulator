import { createFileRoute, Link } from "@tanstack/react-router";
import { useState, useEffect } from "react";
import { AppShell, PageHeader, StatusBadge } from "@/components/app-shell";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { fetchSimbenchNetworks, API_BASE } from "@/lib/api";
import { useNetworks, seedNetworks } from "@/lib/networks-store";
import { ArrowLeft, Cable, Zap, Box, Plug, Play, Loader2 } from "lucide-react";
import { useRole } from "@/hooks/use-role";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/networks/$networkId")({
  head: () => ({
    meta: [
      { title: "Network — DT Lab" },
      { name: "description", content: "Asset summary and details for this network." },
    ],
  }),
  component: NetworkDetail,
});

// ── Page ────────────────────────────────────────────────────────────────────

function NetworkDetail() {
  const { networkId } = Route.useParams();
  const networks = useNetworks();
  const { role } = useRole();
  const canCreateScenario = role === "admin" || role === "researcher";
  const [plotLoading, setPlotLoading] = useState(true);
  const [fetching, setFetching] = useState(networks.length === 0);

  // Fetch networks client-side so the Bearer token (localStorage) is always
  // available. Skip if the store is already seeded (e.g. user came from /networks).
  useEffect(() => {
    if (networks.length > 0) { setFetching(false); return; }
    setFetching(true);
    fetchSimbenchNetworks()
      .then(({ networks: nets }) => { if (nets.length > 0) seedNetworks(nets); })
      .catch(() => {})
      .finally(() => setFetching(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const n = networks.find((x) => x.id === networkId);

  // ── Loading state ──────────────────────────────────────────────────────────
  if (fetching) {
    return (
      <AppShell>
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      </AppShell>
    );
  }

  // ── Not found ──────────────────────────────────────────────────────────────
  if (!n) {
    return (
      <AppShell>
        <Link
          to="/networks"
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground mb-4"
        >
          <ArrowLeft className="h-3 w-3" /> Back to Network Library
        </Link>
        <Card className="p-6 text-sm text-muted-foreground">
          Network <span className="font-mono">{networkId}</span> not found.
        </Card>
      </AppShell>
    );
  }

  // ── Main render ────────────────────────────────────────────────────────────
  const assets = [
    { label: "Buses",        value: n.buses,        icon: Box,  tone: "text-info" },
    { label: "Lines",        value: n.lines,        icon: Cable, tone: "text-primary" },
    { label: "Transformers", value: n.transformers, icon: Zap,  tone: "text-warning-foreground" },
    { label: "Loads",        value: n.loads,        icon: Plug, tone: "text-success" },
  ];

  // Append a cache-buster so the browser always fetches the latest plot HTML
  // instead of serving a stale version from its local cache.
  const plotSrc = n.plot_url ? `${API_BASE}${n.plot_url}?v=${Date.now()}` : null;

  return (
    <AppShell>
      <Link
        to="/networks"
        className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground mb-4"
      >
        <ArrowLeft className="h-3 w-3" /> Back to Network Library
      </Link>

      <PageHeader
        title={n.name}
        description={`${n.type} network · ${n.voltage} · ${n.version}`}
        actions={
          <>
            {canCreateScenario && (
              <Button asChild>
                <Link to="/scenarios" search={{ networkId: n.id }}>
                  <Play className="h-4 w-4 mr-2" /> New scenario
                </Link>
              </Button>
            )}
          </>
        }
      />

      {/* Asset counters */}
      <div className="grid gap-4 grid-cols-2 lg:grid-cols-4 mb-6">
        {assets.map((a) => {
          const Icon = a.icon;
          return (
            <Card key={a.label} className="p-5">
              <div className="flex items-center justify-between">
                <div className="text-xs uppercase tracking-wider text-muted-foreground font-medium">{a.label}</div>
                <Icon className={"h-4 w-4 " + a.tone} />
              </div>
              <div className="mt-2 text-3xl font-semibold">{a.value}</div>
            </Card>
          );
        })}
      </div>

      {/* Main grid: topology + sidebar */}
      <div className={cn(
        "grid grid-cols-1 gap-4",
        "xl:grid-cols-[2fr_1fr] xl:items-start",
      )}>
        {/* Topology */}
        <Card className="p-0 overflow-hidden">
          <div className="px-5 pt-5 pb-3 text-sm font-semibold">Topology overview</div>
          {plotSrc ? (
            <div className="relative h-[600px]">
              {plotLoading && (
                <div className="absolute inset-0 flex items-center justify-center bg-muted/20">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              )}
              <iframe
                src={plotSrc}
                
                className="w-full h-full border-0 block"
                loading="lazy"
                onLoad={() => setPlotLoading(false)}
              />
            </div>
          ) : (
            <div className="h-[600px] flex items-center justify-center text-muted-foreground text-sm border-t border-dashed border-border bg-muted/30">
              No topology plot available
            </div>
          )}
        </Card>

        {/* Sidebar: metadata */}
        <div className="flex flex-col gap-4">
          <Card className="p-5">
            <div className="text-sm font-semibold mb-4">Metadata</div>
            <dl className="space-y-3 text-sm">
              {[
                ["Network ID",    n.id],
                ["Voltage level", n.voltage],
                ["Type",          n.type],
                ["Version",       n.version],
                ["Created",       n.created],
              ].map(([k, v]) => (
                <div key={k} className="flex items-center justify-between">
                  <dt className="text-muted-foreground">{k}</dt>
                  <dd className="font-mono text-xs">{v}</dd>
                </div>
              ))}
              <div className="flex items-center justify-between">
                <dt className="text-muted-foreground">Status</dt>
                <dd><StatusBadge status={n.status} /></dd>
              </div>
            </dl>
          </Card>
        </div>
      </div>
    </AppShell>
  );
}
