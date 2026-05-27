/**
 * Milestone 1 — Real Authentication
 *
 * Token storage  : localStorage key "dtlab.token"
 * Role source    : JWT "role" claim (decoded client-side — no signature check needed,
 *                  the backend validates on every request)
 * Auth event     : "dtlab-auth-change" (replaces the old "dtlab-role-change")
 */

import type { Role } from "./mock-data";

export type { Role };

export type RouteKey =
  | "/dashboard"
  | "/networks"
  | "/scenarios"
  | "/runs"
  | "/results"
  | "/conversion-tools"
  | "/connection-tool-devices"
  | "/users";

export const rolePermissions: Record<Role, RouteKey[]> = {
  admin: [
    "/dashboard",
    "/networks",
    "/scenarios",
    "/runs",
    "/results",
    "/conversion-tools",
    "/connection-tool-devices",
    "/users",
  ],
  researcher: [
    "/dashboard",
    "/networks",
    "/scenarios",
    "/runs",
    "/results",
    "/conversion-tools",
    "/connection-tool-devices",
  ],
  student: ["/dashboard", "/networks", "/runs", "/results"],
};

// ── Token storage ─────────────────────────────────────────────────────────────

const TOKEN_KEY = "dtlab.token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_KEY, token);
  window.dispatchEvent(new Event("dtlab-auth-change"));
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
  window.dispatchEvent(new Event("dtlab-auth-change"));
}

// ── JWT decode (client-side — backend validates on every request) ─────────────

interface JwtPayload {
  sub: string;
  email: string;
  role: Role;
  name: string;
  exp: number;
}

function decodePayload(token: string): JwtPayload | null {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    // Base64url → Base64 → JSON
    const base64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const json = atob(base64);
    return JSON.parse(json) as JwtPayload;
  } catch {
    return null;
  }
}

// ── Role + user info derived from JWT ─────────────────────────────────────────

export function getCurrentRole(): Role | null {
  const token = getToken();
  if (!token) return null;
  const payload = decodePayload(token);
  if (!payload) return null;
  // Treat client-side expiry check as a soft guard only — the backend is authoritative
  if (payload.exp * 1000 < Date.now()) {
    clearToken();
    return null;
  }
  const { role } = payload;
  if (role === "admin" || role === "researcher" || role === "student") return role;
  return null;
}

export function getCurrentUserInfo(): {
  name: string;
  email: string;
  initials: string;
} | null {
  const token = getToken();
  if (!token) return null;
  const payload = decodePayload(token);
  if (!payload) return null;
  const name = payload.name || payload.email || "User";
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const initials =
    parts.length === 0
      ? "?"
      : parts.length === 1
        ? parts[0].slice(0, 2).toUpperCase()
        : (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  return { name, email: payload.email, initials };
}

// ── Access control ────────────────────────────────────────────────────────────

export function hasAccess(role: Role | null, route: RouteKey): boolean {
  if (!role) return false;
  return rolePermissions[role].includes(route);
}
