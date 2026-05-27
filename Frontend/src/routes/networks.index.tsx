import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState, useCallback } from "react";
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
import { useNetworks, seedNetworks, deleteNetwork } from "@/lib/networks-store";
import { fetchSimbenchNetworks } from "@/lib/api";
import { useRole } from "@/hooks/use-role";
import { Upload, Search, ChevronRight, AlertTriangle, RefreshCw, Trash2 } from "lucide-react";

export const Route = createFileRoute("/networks/")({
  head: () => ({
    meta: [
      { title: "Network Library — DT Lab" },
      { name: "description", content: "SimBench distribution network models loaded from the SimBench service." },
    ],
  }),
  component: NetworkLibrary,
});

function NetworkLibrary() {
  const networks = useNetworks();
  const { role } = useRole();
  const isAdmin = role === "admin";
  const [error, setError] = useState<string | null>(null);
  const [fetching, setFetching] = useState(false);
  const [q, setQ] = useState("");
  const [type, setType] = useState<string>("all");
  const [status, setStatus] = useState<string>("all");
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  // Fetch networks client-side so the Bearer token (localStorage) is always
  // available. The route loader was removed because it runs on the server
  // during SSR where localStorage — and therefore the auth token — is not
  // accessible, which caused networks to always be empty on page refresh.
  const loadNetworks = useCallback(() => {
    setFetching(true);
    setError(null);
    fetchSimbenchNetworks()
      .then(({ networks: nets, error: err }) => {
        if (nets.length > 0) seedNetworks(nets);
        if (err) setError(err);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to fetch networks"))
      .finally(() => setFetching(false));
  }, []);

  useEffect(() => { loadNetworks(); }, [loadNetworks]);

  const handleDelete = async (id: string) => {
    setDeleting(id);
    try {
      await deleteNetwork(id);
    } catch (e) {
      console.error("Delete failed", e);
    } finally {
      setDeleting(null);
      setConfirmId(null);
    }
  };

  const filtered = networks.filter(
    (n) =>
      (type === "all" || n.type === type) &&
      (status === "all" || n.status === status) &&
      (q === "" || n.name.toLowerCase().includes(q.toLowerCase())),
  );

  const isEmpty = networks.length === 0;

  return (
    <AppShell>
      <PageHeader
        title="Network Library"
        description="Catalog of SimBench distribution network models. Click a network for asset details."
        actions={
          <Button variant="outline" onClick={loadNetworks} disabled={fetching}>
            <RefreshCw className={"h-4 w-4 mr-2" + (fetching ? " animate-spin" : "")} /> Refresh
          </Button>
        }
      />

      {(isEmpty || error) && (
        <Card className="p-6 mb-6">
          <div className="flex items-start gap-3">
            {error ? (
              <AlertTriangle className="h-5 w-5 text-destructive mt-0.5" />
            ) : (
              <Upload className="h-5 w-5 text-muted-foreground mt-0.5" />
            )}
            <div className="flex-1">
              <div className="font-medium">
                {error ? "Couldn't reach SimBench service" : "No networks loaded yet"}
              </div>
              <div className="text-sm text-muted-foreground mt-1">
                {error
                  ? error
                  : "Configure SIMBENCH_SERVICE_URL in project secrets and point it at your Python service to load real SimBench LV networks."}
              </div>
            </div>
          </div>
        </Card>
      )}

      <Card className="p-4 mb-6">
        <div className="flex flex-col md:flex-row gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search by name…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              className="pl-9"
            />
          </div>
          <Select value={type} onValueChange={setType}>
            <SelectTrigger className="w-full md:w-40"><SelectValue placeholder="Type" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All types</SelectItem>
              <SelectItem value="LV">LV</SelectItem>
              <SelectItem value="MV">MV</SelectItem>
              <SelectItem value="HV">HV</SelectItem>
              <SelectItem value="Mixed">Mixed</SelectItem>
            </SelectContent>
          </Select>
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="w-full md:w-44"><SelectValue placeholder="Status" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="validated">Validated</SelectItem>
              <SelectItem value="draft">Draft</SelectItem>
              <SelectItem value="archived">Archived</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </Card>

      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted/40">
              <tr className="text-left text-xs uppercase tracking-wider text-muted-foreground">
                <th className="py-3 px-4 font-medium">Name</th>
                <th className="py-3 px-4 font-medium">Voltage</th>
                <th className="py-3 px-4 font-medium">Type</th>
                <th className="py-3 px-4 font-medium">Created</th>
                <th className="py-3 px-4 font-medium">Version</th>
                <th className="py-3 px-4 font-medium">Status</th>
                <th className="py-3 px-4 font-medium text-right">Assets</th>
                <th className="py-3 px-4" />
              </tr>
            </thead>
            <tbody>
              {filtered.map((n) => (
                <tr key={n.id} className="border-t border-border hover:bg-muted/30 transition-colors">
                  <td className="py-3 px-4 font-medium">
                    <Link to="/networks/$networkId" params={{ networkId: n.id }} className="hover:text-primary">
                      {n.name}
                    </Link>
                    <div className="text-xs text-muted-foreground font-mono">{n.id}</div>
                  </td>
                  <td className="py-3 px-4 font-mono text-xs">{n.voltage}</td>
                  <td className="py-3 px-4">{n.type}</td>
                  <td className="py-3 px-4 text-muted-foreground">{n.created}</td>
                  <td className="py-3 px-4 font-mono text-xs">{n.version}</td>
                  <td className="py-3 px-4"><StatusBadge status={n.status} /></td>
                  <td className="py-3 px-4 text-right text-xs text-muted-foreground">
                    {n.buses}b · {n.lines}l · {n.transformers}t
                  </td>
                  <td className="py-3 px-4">
                    <div className="flex items-center justify-end gap-1">
                      <Link
                        to="/networks/$networkId"
                        params={{ networkId: n.id }}
                        className="text-muted-foreground hover:text-primary inline-flex"
                      >
                        <ChevronRight className="h-4 w-4" />
                      </Link>
                      {isAdmin && (confirmId === n.id ? (
                        <>
                          <Button
                            variant="destructive"
                            size="sm"
                            disabled={deleting === n.id}
                            onClick={() => handleDelete(n.id)}
                            className="h-7 px-2 text-xs"
                          >
                            {deleting === n.id ? "Deleting…" : "Confirm"}
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
                          onClick={() => setConfirmId(n.id)}
                          className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                          title="Delete network"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && !isEmpty && (
                <tr>
                  <td colSpan={8} className="text-center py-12 text-muted-foreground text-sm">
                    No networks match your filters.
                  </td>
                </tr>
              )}
              {isEmpty && (
                <tr>
                  <td colSpan={8} className="text-center py-12 text-muted-foreground text-sm">
                    {fetching ? "Loading networks…" : "No networks loaded."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </AppShell>
  );
}
