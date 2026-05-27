// Server-only helpers for the SimBench network service.
// This file must not be imported from client code (Vite import-protection
// blocks `*.server.ts` from the client bundle).

import { z } from "zod";
import type { Network } from "@/lib/mock-data";

// Schema for one entry returned by the Python service's GET /networks.
// We accept extra fields and a few aliases so the contract is forgiving.
const RawNetworkSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1).optional(),
  voltage: z.string().optional(),
  type: z.string().optional(),
  status: z.string().optional(),
  created: z.string().optional(),
  version: z.string().optional(),
  buses: z.number().int().nonnegative().optional(),
  lines: z.number().int().nonnegative().optional(),
  transformers: z.number().int().nonnegative().optional(),
  loads: z.number().int().nonnegative().optional(),
  plot_url: z.string().nullable().optional(),
});

type RawNetwork = z.infer<typeof RawNetworkSchema>;

function today(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function normalizeStatus(s: string | undefined): Network["status"] {
  if (s === "validated" || s === "draft" || s === "archived") return s;
  // SimBench service uses "available" — treat as validated for the UI.
  return "validated";
}

function normalizeType(t: string | undefined): Network["type"] {
  if (t === "LV" || t === "MV" || t === "HV" || t === "Mixed") return t;
  return "LV";
}

function toNetwork(raw: RawNetwork): Network {
  return {
    id: raw.id,
    name: raw.name ?? `SimBench ${raw.id}`,
    voltage: raw.voltage ?? "0.4 kV",
    type: normalizeType(raw.type),
    created: raw.created ?? today(),
    version: raw.version ?? "v1.0",
    status: normalizeStatus(raw.status),
    buses: raw.buses ?? 0,
    lines: raw.lines ?? 0,
    transformers: raw.transformers ?? 0,
    loads: raw.loads ?? 0,
    plot_url: raw.plot_url ?? null,
  };
}

export interface FetchNetworksResult {
  networks: Network[];
  error: string | null;
  serviceUrl: string | null;
}

export async function fetchNetworksFromService(input: {
  serviceUrl?: string | null;
  serviceToken?: string | null;
}): Promise<FetchNetworksResult> {
  const baseUrl = input.serviceUrl?.trim();
  if (!baseUrl) {
    return {
      networks: [],
      error: null,
      serviceUrl: null,
    };
  }

  const normalizedBase = baseUrl.replace(/\/+$/, "");
  const url = normalizedBase + "/networks";
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = input.serviceToken?.trim();
  if (token) headers.Authorization = `Bearer ${token}`;

  try {
    const res = await fetch(url, { headers });
    if (!res.ok) {
      console.error(`SimBench service returned ${res.status} ${res.statusText}`);
      return {
        networks: [],
        error: `SimBench service returned ${res.status}`,
        serviceUrl: normalizedBase,
      };
    }

    const json = await res.json();
    if (!Array.isArray(json)) {
      console.error("SimBench service did not return an array");
      return {
        networks: [],
        error: "Unexpected response from SimBench service",
        serviceUrl: normalizedBase,
      };
    }

    const parsed: Network[] = [];
    for (const item of json) {
      const result = RawNetworkSchema.safeParse(item);
      if (result.success) {
        parsed.push(toNetwork(result.data));
      } else {
        console.warn("Skipping malformed SimBench entry:", result.error.message);
      }
    }

    return { networks: parsed, error: null, serviceUrl: normalizedBase };
  } catch (err) {
    console.error("Failed to fetch SimBench networks:", err);
    return {
      networks: [],
      error: "Could not reach the SimBench service",
      serviceUrl: normalizedBase,
    };
  }
}
