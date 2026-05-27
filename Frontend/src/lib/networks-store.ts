// Reactive store over the `networks` array in mock-data. The array starts
// empty and is seeded at runtime from the SimBench service via `seedNetworks`.
// Mutating in place keeps the static `networks` export in sync for any code
// that imports it directly (dashboard, comparison, results, runs-store).
import { useSyncExternalStore } from "react";
import { networks as networksArray, type Network } from "./mock-data";
import { seedRunsFromBackend } from "./runs-store";
import { deleteNetworkApi } from "./api";

type Listener = () => void;
const listeners = new Set<Listener>();
let snapshot: Network[] = [...networksArray];

function emit() {
  snapshot = [...networksArray];
  listeners.forEach((l) => l());
}

function subscribe(l: Listener) {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}

function getSnapshot() {
  return snapshot;
}

export function useNetworks(): Network[] {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

export function getAllNetworks(): Network[] {
  return snapshot;
}

/**
 * Replace the in-memory network list (e.g. after fetching from the SimBench
 * service). Preserves any networks added at runtime that are not in the new
 * list (such as converted networks created via `addConvertedNetwork`).
 */
export function seedNetworks(list: Network[]): void {
  const incomingIds = new Set(list.map((n) => n.id));
  // Keep runtime-added entries (converted networks) that aren't in the seed.
  const preserved = networksArray.filter(
    (n) => !incomingIds.has(n.id) && n.id.startsWith("net-conv-"),
  );
  networksArray.length = 0;
  networksArray.push(...list, ...preserved);
  emit();
  // Seed historical runs from backend storage now that networks are loaded.
  seedRunsFromBackend();
}

/** Remove a network from the in-memory store immediately (no API call). */
export function removeNetwork(networkId: string): void {
  const idx = networksArray.findIndex((n) => n.id === networkId);
  if (idx !== -1) {
    networksArray.splice(idx, 1);
    emit();
  }
}

/**
 * Delete a network from the backend (DB + networks.json) and remove it from
 * the in-memory store. Throws on network/API error.
 */
export async function deleteNetwork(networkId: string): Promise<void> {
  await deleteNetworkApi(networkId);
  removeNetwork(networkId);
}

let nextConvertedCounter = 100;
function nextConvertedId() {
  nextConvertedCounter += 1;
  return `net-conv-${nextConvertedCounter}`;
}

function today() {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/**
 * Add a converted network (e.g. from OpenDSS -> pandapower) to the library.
 * Returns the newly created network's id.
 */
export function findConvertedNetwork(
  sourceLabel: string,
  target = "pandapower",
): Network | undefined {
  const name = `${sourceLabel} - ${target}`;
  return networksArray.find((n) => n.name === name);
}

export function addConvertedNetwork(input: {
  sourceLabel: string; // e.g. "Network 1"
  target?: string; // defaults to "pandapower"
}): { network: Network; alreadyExisted: boolean } {
  const target = input.target ?? "pandapower";
  const name = `${input.sourceLabel} - ${target}`;

  const existing = networksArray.find((n) => n.name === name);
  if (existing) {
    return { network: existing, alreadyExisted: true };
  }

  const buses = 20 + Math.floor(Math.random() * 40);
  const lines = buses - 1 + Math.floor(Math.random() * 5);
  const transformers = 1 + Math.floor(Math.random() * 3);
  const loads = Math.floor(buses * 0.7);

  const newNet: Network = {
    id: nextConvertedId(),
    name,
    voltage: "20 kV",
    type: "MV",
    created: today(),
    version: "v1.0",
    status: "validated",
    buses,
    lines,
    transformers,
    loads,
  };

  networksArray.unshift(newNet);
  emit();
  return { network: newNet, alreadyExisted: false };
}