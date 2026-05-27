import { Link, useLocation, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import {
  LayoutGrid,
  Network,
  FlaskConical,
  PlayCircle,
  ChartSpline,
  Wrench,
  Cable,
  Zap,
  LogOut,

  Search,
  Users as UsersIcon,
} from "lucide-react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { clearToken, getCurrentUserInfo, hasAccess, type RouteKey } from "@/lib/auth";
import { useRole } from "@/hooks/use-role";
import { useNetworks } from "@/lib/networks-store";
import { useRuns } from "@/lib/runs-store";
import { getAllScenarios } from "@/lib/scenarios-store";

const navItems: { to: RouteKey; label: string; icon: typeof LayoutGrid }[] = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutGrid },
  { to: "/networks", label: "Network Library", icon: Network },
  { to: "/scenarios", label: "Scenario Builder", icon: FlaskConical },
  { to: "/runs", label: "Simulation Runs", icon: PlayCircle },
  { to: "/results", label: "Results & Analytics", icon: ChartSpline },
  { to: "/conversion-tools", label: "Conversion Tools", icon: Wrench },
  { to: "/connection-tool-devices", label: "Live Testbed", icon: Cable },
  { to: "/users", label: "Users", icon: UsersIcon },
];

const knownRoutes: RouteKey[] = [
  "/dashboard",
  "/networks",
  "/scenarios",
  "/runs",
  "/results",
  "/conversion-tools",
  "/connection-tool-devices",
  "/users",
];

// ── Global search command palette ────────────────────────────────────────────

function GlobalSearch() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const networks = useNetworks();
  const runs = useRuns();

  // Ctrl+K / ⌘K shortcut
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen(true);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  const completedRuns = runs
    .filter((r) => r.status === "completed")
    .slice(0, 12);

  const scenarios = getAllScenarios().slice(0, 12);

  function go(to: string, search?: Record<string, string>) {
    setOpen(false);
    navigate({ to, search } as Parameters<typeof navigate>[0]);
  }

  return (
    <>
      {/* Trigger — looks like a search box */}
      <div
        className="relative flex-1 max-w-md cursor-pointer"
        onClick={() => setOpen(true)}
      >
        <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          readOnly
          placeholder="Search networks, scenarios, runs…"
          className="pl-9 h-9 bg-muted/40 border-transparent cursor-pointer select-none"
          onFocus={() => setOpen(true)}
        />
        <kbd className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 hidden sm:inline-flex h-5 items-center gap-1 rounded border border-border bg-muted px-1.5 text-[10px] font-medium text-muted-foreground">
          ⌘K
        </kbd>
      </div>

      {/* Palette */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="p-0 gap-0 overflow-hidden max-w-lg">
          <Command>
            <CommandInput placeholder="Search networks, scenarios, runs…" autoFocus />
            <CommandList className="max-h-96">
              <CommandEmpty>No results found.</CommandEmpty>

              {/* Pages */}
              <CommandGroup heading="Pages">
                {navItems.map((item) => {
                  const Icon = item.icon;
                  return (
                    <CommandItem
                      key={item.to}
                      value={item.label}
                      onSelect={() => go(item.to)}
                    >
                      <Icon className="h-4 w-4 mr-2 text-muted-foreground shrink-0" />
                      {item.label}
                    </CommandItem>
                  );
                })}
              </CommandGroup>

              {/* Networks */}
              {networks.length > 0 && (
                <CommandGroup heading="Networks">
                  {networks.map((n) => (
                    <CommandItem
                      key={n.id}
                      value={`${n.name} ${n.id}`}
                      onSelect={() => go(`/networks/${n.id}`)}
                    >
                      <Network className="h-4 w-4 mr-2 text-muted-foreground shrink-0" />
                      <span className="truncate">{n.name}</span>
                      <span className="ml-auto text-xs text-muted-foreground shrink-0 pl-2">
                        {n.voltage}
                      </span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              )}

              {/* Scenarios */}
              {scenarios.length > 0 && (
                <CommandGroup heading="Scenarios">
                  {scenarios.map((s) => (
                    <CommandItem
                      key={s.id}
                      value={`${s.name} ${s.id}`}
                      onSelect={() => go("/scenarios")}
                    >
                      <FlaskConical className="h-4 w-4 mr-2 text-muted-foreground shrink-0" />
                      <span className="truncate">{s.name}</span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              )}

              {/* Runs */}
              {completedRuns.length > 0 && (
                <CommandGroup heading="Recent Runs">
                  {completedRuns.map((r) => {
                    const networkId =
                      (r as typeof r & { networkId?: string }).networkId ?? "";
                    return (
                      <CommandItem
                        key={r.id}
                        value={`${r.id} ${r.scenarioName}`}
                        onSelect={() =>
                          go("/results", { runId: r.id, networkId })
                        }
                      >
                        <ChartSpline className="h-4 w-4 mr-2 text-muted-foreground shrink-0" />
                        <span className="truncate font-mono text-xs">{r.id}</span>
                        <span className="ml-2 truncate text-xs text-muted-foreground">
                          {r.scenarioName}
                        </span>
                      </CommandItem>
                    );
                  })}
                </CommandGroup>
              )}
            </CommandList>
          </Command>
        </DialogContent>
      </Dialog>
    </>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

export function AppShell({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { role, ready } = useRole();

  const currentRouteKey = ("/" + location.pathname.split("/")[1]) as RouteKey;
  const isKnown = knownRoutes.includes(currentRouteKey);
  const allowed = role ? hasAccess(role, currentRouteKey) : false;

  useEffect(() => {
    if (!ready) return;
    if (!role) {
      navigate({ to: "/" });
    } else if (isKnown && !allowed) {
      navigate({ to: "/dashboard" });
    }
  }, [ready, role, isKnown, allowed, navigate]);

  if (!ready || !role || (isKnown && !allowed)) {
    return null;
  }

  const visibleNav = navItems.filter((item) => hasAccess(role, item.to));

  const userInfo = getCurrentUserInfo();

  const handleSignOut = (e: React.MouseEvent) => {
    e.preventDefault();
    clearToken();
    navigate({ to: "/" });
  };

  return (
    <div className="flex min-h-screen w-full bg-background">
      {/* Sidebar */}
      <aside className="hidden md:flex w-64 shrink-0 flex-col bg-sidebar text-sidebar-foreground border-r border-sidebar-border">
        <div className="flex items-center gap-2 px-5 h-16 border-b border-sidebar-border">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-sidebar-primary text-sidebar-primary-foreground">
            <Zap className="h-5 w-5" />
          </div>
          <div className="leading-tight">
            <div className="text-sm font-semibold tracking-tight">DT Lab</div>
            <div className="text-[10px] uppercase tracking-widest text-sidebar-foreground/60">
              Grid Studio
            </div>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-1">
          <div className="px-2 pb-2 text-[10px] font-semibold uppercase tracking-widest text-sidebar-foreground/50">
            Workspace
          </div>
          {visibleNav.map((item) => {
            const active = location.pathname.startsWith(item.to);
            const Icon = item.icon;
            return (
              <Link
                key={item.to}
                to={item.to}
                className={
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors " +
                  (active
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground")
                }
              >
                <Icon className="h-4 w-4 shrink-0" />
                <span className="truncate">{item.label}</span>
                {active && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-sidebar-primary" />}
              </Link>
            );
          })}
        </nav>

        <div className="border-t border-sidebar-border p-3">
          <a
            href="/"
            onClick={handleSignOut}
            className="flex items-center gap-3 rounded-md px-3 py-2 text-sm text-sidebar-foreground/70 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground cursor-pointer"
          >
            <LogOut className="h-4 w-4" />
            Sign out
          </a>
        </div>
      </aside>

      {/* Main */}
      <div className="flex flex-1 flex-col min-w-0">
        <header className="sticky top-0 z-30 flex h-16 items-center gap-4 border-b border-border bg-card/80 backdrop-blur px-4 md:px-6">
          <GlobalSearch />
          <div className="ml-auto flex items-center gap-3">

            <div className="hidden sm:flex items-center gap-3 pl-3 border-l border-border">
              <div className="text-right leading-tight">
                <div className="text-sm font-medium">{userInfo?.name ?? "User"}</div>
                <div className="text-xs text-muted-foreground capitalize">{role}</div>
              </div>
              <Avatar className="h-9 w-9">
                <AvatarFallback className="bg-primary text-primary-foreground text-xs font-semibold">
                  {userInfo?.initials ?? "?"}
                </AvatarFallback>
              </Avatar>
            </div>
          </div>
        </header>

        <main className="flex-1 p-4 md:p-8 max-w-[1600px] w-full mx-auto">{children}</main>
      </div>
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4 mb-6">
      <div>
        <h1 className="text-2xl md:text-3xl font-semibold tracking-tight text-foreground">
          {title}
        </h1>
        {description && (
          <p className="mt-1 text-sm text-muted-foreground max-w-2xl">{description}</p>
        )}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    completed: "bg-success/15 text-success border-success/30",
    validated: "bg-success/15 text-success border-success/30",
    running: "bg-info/15 text-info border-info/30",
    queued: "bg-muted text-muted-foreground border-border",
    draft: "bg-muted text-muted-foreground border-border",
    failed: "bg-destructive/15 text-destructive border-destructive/30",
    archived: "bg-muted text-muted-foreground/70 border-border",
  };
  return (
    <Badge variant="outline" className={"capitalize font-medium " + (map[status] ?? "")}>
      {status}
    </Badge>
  );
}

export function SeverityBadge({ severity }: { severity: string }) {
  const map: Record<string, string> = {
    low: "bg-info/15 text-info border-info/30",
    medium: "bg-warning/20 text-warning-foreground border-warning/40",
    high: "bg-destructive/15 text-destructive border-destructive/30",
    critical: "bg-destructive text-destructive-foreground border-destructive",
  };
  return (
    <Badge variant="outline" className={"capitalize font-medium " + (map[severity] ?? "")}>
      {severity}
    </Badge>
  );
}
