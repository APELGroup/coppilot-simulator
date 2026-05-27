import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import {
  Zap,
  ArrowRight,
  PlayCircle,
  AlertTriangle,
  Network,
  HardHat,
  Book,
  ShieldCheck,
  Wrench,
  Cable,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card } from "@/components/ui/card";
import { setToken } from "@/lib/auth";
import { loginApi, registerApi } from "@/lib/api";
export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Sign in — Digital Twin Lab" },
      { name: "description", content: "Sign in to the Digital Twin Laboratory Platform for electrical distribution network studies." },
    ],
  }),
  component: LoginPage,
});

const features = [
  { icon: PlayCircle, title: "Power-flow & time-series", desc: "Run balanced and unbalanced studies on MV/LV grids." },
  { icon: AlertTriangle, title: "Violation detection", desc: "Auto-flag voltage and overload limits across runs." },
  { icon: Wrench, title: "Conversion and Validation", desc: "Convert networks from other formats to pandapower and validate their integrity." },
  { icon: Cable, title: "Live Testbed", desc: "Connect edge devices, estimate flexibility regions and visualize the FOR in real-time." },
];

const stats = [
  { v: "MV & LV grids", l: "Multi-voltage network support" },
  { v: "Real-time edge", l: "Live device connectivity" },
  { v: "Open standards", l: "pandapower & SimBench based" },
];

function LoginPage() {
  const navigate = useNavigate();
  const [isRegisterMode, setIsRegisterMode] = useState(false);
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [selectedRole, setSelectedRole] = useState<"student" | "researcher" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const data = await loginApi(email, password);
      setToken(data.access_token);
      navigate({ to: "/dashboard" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed — please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedRole) return;
    setError(null);
    setLoading(true);
    try {
      const data = await registerApi(username.trim(), email.trim(), password, selectedRole);
      setToken(data.access_token);
      navigate({ to: "/dashboard" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed — please try again.");
    } finally {
      setLoading(false);
    }
  };

  const switchMode = (register: boolean) => {
    setIsRegisterMode(register);
    setError(null);
    setPassword("");
    setConfirmPassword("");
  };

  return (
    <div className="min-h-screen flex flex-col lg:flex-row bg-background">
      {/* Left brand panel */}
      <div className="relative hidden lg:flex flex-col w-[55%] bg-sidebar text-sidebar-foreground p-8 xl:p-12 2xl:p-16 overflow-hidden">
        <div
          className="absolute inset-0 opacity-30"
          style={{
            backgroundImage:
              "radial-gradient(circle at 20% 20%, oklch(0.7 0.16 200 / 0.4), transparent 50%), radial-gradient(circle at 80% 70%, oklch(0.45 0.15 240 / 0.5), transparent 50%)",
          }}
        />
        <div
          className="absolute inset-0 opacity-[0.07]"
          style={{
            backgroundImage:
              "linear-gradient(oklch(0.7 0.16 200) 1px, transparent 1px), linear-gradient(90deg, oklch(0.7 0.16 200) 1px, transparent 1px)",
            backgroundSize: "40px 40px",
          }}
        />

        {/* Logo */}
        <div className="group relative flex items-center gap-3 cursor-default">
          <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground shadow-lg shadow-sidebar-primary/20 transition-all duration-300 ease-out group-hover:shadow-xl group-hover:shadow-sidebar-primary/40 group-hover:-translate-y-0.5">
            <Zap className="h-6 w-6 transition-transform duration-300 ease-out group-hover:scale-110" />
          </div>
          <div>
            <div className="text-lg font-semibold tracking-tight transition-colors duration-300 group-hover:text-sidebar-primary">DT Lab</div>
            <div className="text-xs uppercase tracking-widest text-sidebar-foreground/60">
              Grid Studio
            </div>
          </div>
        </div>

        {/* Headline + content — anchored vertically with controlled spacing */}
        <div className="relative mt-12 xl:mt-16 space-y-6">
          <div className="inline-flex items-center gap-2 rounded-full border border-sidebar-border bg-sidebar-accent/40 px-3 py-1 text-xs font-medium text-sidebar-primary">
            <span className="h-1.5 w-1.5 rounded-full bg-sidebar-primary animate-pulse" />
            Pandapower based platform for distribution network studies
          </div>
          <h1 className="text-3xl xl:text-4xl font-semibold tracking-tight leading-[1.15]">
            Digital Twin Laboratory for Distribution Networks
          </h1>
          <p className="text-sidebar-foreground/70 text-[15px] leading-relaxed">
            Model, simulate and analyze MV and LV grids. Run power-flow and
            time-series studies, detect violations, convert networks, and connect
            real edge devices to estimate flexibility operating regions — all in one workspace.
          </p>

          {/* Feature bullets */}
          <ul className="grid sm:grid-cols-2 gap-3 pt-2">
            {features.map((f) => {
              const Icon = f.icon;
              return (
                <li
                  key={f.title}
                  className="group flex items-start gap-3 rounded-lg border border-sidebar-border/60 bg-sidebar-accent/20 backdrop-blur-sm p-3 transition-all duration-300 ease-out hover:-translate-y-0.5 hover:border-sidebar-primary/50 hover:bg-sidebar-accent/40 hover:shadow-lg hover:shadow-sidebar-primary/10"
                >
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-sidebar-primary/15 text-sidebar-primary transition-transform duration-300 ease-out group-hover:scale-105">
                    <Icon className="h-4 w-4" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-medium leading-tight transition-colors duration-300 group-hover:text-sidebar-primary">{f.title}</div>
                    <div className="text-xs text-sidebar-foreground/60 mt-0.5 leading-snug">
                      {f.desc}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>

          {/* Stats */}
          <div className="grid grid-cols-3 gap-4 pt-4 border-t border-sidebar-border/60 mt-2">
            {stats.map((s) => (
              <div key={s.l} className="group cursor-default transition-transform duration-300 ease-out hover:-translate-y-0.5">
                <div className="text-sm font-semibold text-sidebar-primary transition-all duration-300 group-hover:brightness-125">
                  {s.v}
                </div>
                <div className="text-xs text-sidebar-foreground/60 mt-0.5 transition-colors duration-300 group-hover:text-sidebar-foreground/80">{s.l}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Footer */}
        <div className="relative mt-auto pt-10 flex items-center justify-between text-xs text-sidebar-foreground/50">
          <span>© 2026 • APEL - University of Patras</span>
          <span className="inline-flex items-center gap-1.5">
            <ShieldCheck className="h-3.5 w-3.5" />
            JWT secured
          </span>
        </div>
      </div>

      {/* Right form panel */}
      <div className="flex-1 flex items-center justify-center p-6 md:p-10 bg-muted/20">
        <Card className="w-full max-w-md p-8 md:p-10 border-border shadow-2xl shadow-foreground/[0.06]">
          <div className="lg:hidden flex items-center gap-2 mb-6">
            <div className="flex h-9 w-9 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <Zap className="h-5 w-5" />
            </div>
            <div className="font-semibold">DT Lab</div>
          </div>

          <div className="mb-7">
            <div className="text-xs uppercase tracking-widest text-primary font-semibold mb-2">
              {isRegisterMode ? "Register" : "Sign in"}
            </div>
            <h2 className="text-2xl md:text-3xl font-semibold tracking-tight">
              {isRegisterMode ? "Create account" : "Welcome back"}
            </h2>
            <p className="text-sm text-muted-foreground mt-1.5">
              {isRegisterMode
                ? "Start using your workspace."
                : "Access your simulation workspace and recent runs."}
            </p>
          </div>

          {isRegisterMode ? (
            <form onSubmit={handleRegister} className="space-y-5">
              <div className="space-y-1.5">
                <Label htmlFor="reg-username" className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Full name
                </Label>
                <Input
                  id="reg-username"
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  placeholder="Jane Doe"
                  className="h-11"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="reg-email" className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Email
                </Label>
                <Input
                  id="reg-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  placeholder="you@dtlab.io"
                  className="h-11"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="reg-password" className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Password
                </Label>
                <Input
                  id="reg-password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  className="h-11"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="reg-confirm" className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Confirm password
                </Label>
                <Input
                  id="reg-confirm"
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                  aria-invalid={confirmPassword.length > 0 && password !== confirmPassword}
                  className={
                    "h-11 " +
                    (confirmPassword.length > 0 && password !== confirmPassword
                      ? "border-destructive focus-visible:ring-destructive"
                      : "")
                  }
                />
                {confirmPassword.length > 0 && password !== confirmPassword && (
                  <p className="text-xs text-destructive mt-1">Passwords do not match</p>
                )}
              </div>

              <div className="space-y-1.5">
                <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Account type
                </Label>
                <div className="grid grid-cols-2 gap-2">
                  {(["student", "researcher"] as const).map((r) => {
                    const active = selectedRole === r;
                    const Icon = r === "student" ? Book : HardHat;
                    return (
                      <button
                        key={r}
                        type="button"
                        onClick={() => setSelectedRole(r)}
                        aria-pressed={active}
                        className={
                          "group flex items-center justify-between rounded-md border px-3 py-2 text-xs font-medium capitalize transition-all " +
                          (active
                            ? "border-primary bg-primary/10 text-foreground shadow-sm shadow-primary/20"
                            : "border-border bg-muted/30 text-foreground/80 hover:border-primary/40 hover:bg-primary/5 hover:text-foreground")
                        }
                      >
                        <span>{r}</span>
                        <Icon
                          className={
                            "h-3 w-3 transition-all " +
                            (active
                              ? "text-primary opacity-100 translate-x-0"
                              : "text-muted-foreground opacity-0 -translate-x-1 group-hover:opacity-100 group-hover:translate-x-0 group-hover:text-primary")
                          }
                        />
                      </button>
                    );
                  })}
                </div>
              </div>

              {error && (
                <p className="text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-md px-3 py-2">
                  {error}
                </p>
              )}

              <Button
                type="submit"
                size="lg"
                disabled={loading || !selectedRole || !username.trim() || !password || password !== confirmPassword}
                className="w-full h-11 mt-2 font-semibold shadow-md shadow-primary/25 transition-all duration-300 ease-out hover:-translate-y-0.5 hover:shadow-xl hover:shadow-primary/40 hover:brightness-105 group disabled:opacity-50 disabled:hover:translate-y-0 disabled:hover:shadow-md disabled:cursor-not-allowed"
              >
                {loading ? "Creating account…" : "Register"}
                {!loading && <ArrowRight className="ml-2 h-4 w-4 transition-transform duration-300 ease-out group-hover:translate-x-1" />}
              </Button>

              <div className="text-center text-xs text-muted-foreground pt-1">
                Already have an account?{" "}
                <button
                  type="button"
                  onClick={() => switchMode(false)}
                  className="text-primary hover:underline font-medium"
                >
                  Sign in
                </button>
              </div>
            </form>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-5">
              <div className="space-y-1.5">
                <Label htmlFor="email" className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Email
                </Label>
                <Input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  placeholder="you@dtlab.io"
                  className="h-11"
                />
              </div>
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <Label htmlFor="password" className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                    Password
                  </Label>
                </div>
                <Input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  className="h-11"
                />
              </div>

              {error && (
                <p className="text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-md px-3 py-2">
                  {error}
                </p>
              )}

              <Button
                type="submit"
                size="lg"
                disabled={loading}
                className="w-full h-11 mt-2 font-semibold shadow-md shadow-primary/25 transition-all duration-300 ease-out hover:-translate-y-0.5 hover:shadow-xl hover:shadow-primary/40 hover:brightness-105 group disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {loading ? "Signing in…" : "Sign in"}
                {!loading && <ArrowRight className="ml-2 h-4 w-4 transition-transform duration-300 ease-out group-hover:translate-x-1" />}
              </Button>

              <div className="text-center text-xs text-muted-foreground pt-1">
                Don't have an account?{" "}
                <button
                  type="button"
                  onClick={() => switchMode(true)}
                  className="text-primary hover:underline font-medium"
                >
                  Register
                </button>
              </div>
            </form>
          )}
        </Card>
      </div>
    </div>
  );
}