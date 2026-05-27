// Shared types and runtime stores for the Digital Twin Lab platform.
//
// Note: this file no longer contains any mock / demo / sample data. It only
// defines the shared TypeScript types and the (initially empty) in-memory
// arrays that act as runtime stores. Real data is loaded from the backend
// (SimBench service / simulation results) and pushed into these arrays via
// the corresponding store helpers (`networks-store`, `runs-store`).

export type Role = "admin" | "researcher" | "student";

export interface User {
  name: string;
  email: string;
  role: Role;
  initials: string;
}

// The currently signed-in user is the only seeded user (kept on purpose so
// the app shell has someone to render in the avatar / header). Per-user
// management still happens in `users-store`.
export const currentUser: User = {
  name: "Dr. Elena Marchetti",
  email: "elena.marchetti@dtlab.io",
  role: "researcher",
  initials: "EM",
};

export interface Network {
  id: string;
  name: string;
  voltage: string;
  type: "MV" | "LV" | "HV" | "Mixed";
  created: string;
  version: string;
  status: "validated" | "draft" | "archived";
  buses: number;
  lines: number;
  transformers: number;
  loads: number;
  plot_url?: string | null;
}

export const networks: Network[] = [];

export type SimType = "power_flow" | "time_series";
export type RunStatus = "queued" | "running" | "completed" | "failed";

export interface Scenario {
  id: string;
  name: string;
  networkId: string;
  simType: SimType;
  mode: "balanced" | "unbalanced";
  horizon: string;
  timestep: string;
  createdBy: string;
  createdAt: string;
}

export const scenarios: Scenario[] = [];

export interface Run {
  id: string;
  scenarioId: string;
  scenarioName: string;
  networkName: string;
  networkId?: string;
  status: RunStatus;
  startedAt: string;
  duration: string;
  progress: number;
  violations: number;
}

export const runs: Run[] = [];

export type ViolationCategory =
  | "under_voltage"
  | "over_voltage"
  | "line_overload"
  | "transformer_overload";
export type Severity = "low" | "medium" | "high" | "critical";

export interface Violation {
  id: string;
  category: ViolationCategory;
  asset: string;
  value: string;
  limit: string;
  severity: Severity;
  time: string;
  runId: string;
}

export const violations: Violation[] = [];

export type ComponentType = "bus" | "line" | "transformer";
