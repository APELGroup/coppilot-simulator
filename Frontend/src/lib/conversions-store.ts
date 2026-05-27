/**
 * Reactive store for network conversion/validation events shown in the
 * Recent Activity feed on the dashboard.
 *
 * Events are added explicitly via `addConversionEvent()` — called from
 * both the quick-save (conversion-only) and the full validated-save paths
 * in Conversion Tools. They are persisted in localStorage so they survive
 * a page refresh (up to MAX_EVENTS most recent entries are kept).
 *
 * We do NOT seed from the full networks list so that only events that
 * actually happened in this browser are shown — no bulk-import of old
 * historical conversions.
 */
import { useSyncExternalStore } from "react";

export interface ConversionEvent {
  networkId: string;
  networkName: string;
  /** YYYY-MM-DD HH:MM — used directly as sort key and display time. */
  convertedAt: string;
  convertedBy: string;
  /** "conversion" = no simulation; "validation" = converted + validated. */
  type: "conversion" | "validation";
}

const STORAGE_KEY = "dtlab.conversion-events";
const MAX_EVENTS = 20;

function loadFromStorage(): ConversionEvent[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as ConversionEvent[]) : [];
  } catch {
    return [];
  }
}

function saveToStorage(evts: ConversionEvent[]): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(evts.slice(0, MAX_EVENTS)));
  } catch {}
}

const events: ConversionEvent[] = loadFromStorage();
type Listener = () => void;
const listeners = new Set<Listener>();
let snapshot: ConversionEvent[] = [...events];

function emit() {
  snapshot = [...events];
  saveToStorage(events);
  listeners.forEach((l) => l());
}

function subscribe(l: Listener) {
  listeners.add(l);
  return () => { listeners.delete(l); };
}

function getSnapshot() {
  return snapshot;
}

export function useConversions(): ConversionEvent[] {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

export function getAllConversions(): ConversionEvent[] {
  return snapshot;
}

/**
 * Add (or replace) a conversion/validation event.
 * Replaces any existing event for the same networkId so re-saving
 * always shows the most recent status.
 */
export function addConversionEvent(event: ConversionEvent): void {
  const idx = events.findIndex((e) => e.networkId === event.networkId);
  if (idx !== -1) events.splice(idx, 1);
  events.unshift(event);
  // Keep only the most recent MAX_EVENTS
  if (events.length > MAX_EVENTS) events.splice(MAX_EVENTS);
  emit();
}
