import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";

const RunInputSchema = z.object({
  networkId: z.string().min(1),
  horizon: z.enum(["day", "month", "year"]),
  year: z.number().int(),
  month: z.number().int().min(1).max(12),
  day: z.number().int().min(1).max(31),
  mode: z.enum(["balanced", "unbalanced"]),
});

export const runSimulation = createServerFn({ method: "POST" })
  .inputValidator((input: unknown) => RunInputSchema.parse(input))
  .handler(async ({ data }) => {
    const baseUrl = process.env.SIMBENCH_SERVICE_URL?.trim();
    const token = process.env.SIMBENCH_SERVICE_TOKEN?.trim();
    if (!baseUrl) {
      return { ok: false as const, error: "SIMBENCH_SERVICE_URL is not configured" };
    }

    const normalizedBase = baseUrl.replace(/\/+$/, "");
    const url = `${normalizedBase}/networks/${encodeURIComponent(data.networkId)}/run`;
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "application/json",
    };
    if (token) headers.Authorization = `Bearer ${token}`;

    const body = {
      horizon: data.horizon,
      year: data.year,
      month: data.month,
      day: data.day,
      mode: data.mode,
    };

    try {
      const res = await fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
      });
      const text = await res.text();
      if (!res.ok) {
        return {
          ok: false as const,
          error: `Simulation service returned ${res.status}`,
          payload: text,
        };
      }
      let parsed: any = null;
      try {
        parsed = text ? JSON.parse(text) : null;
      } catch {
        parsed = null;
      }
      // Try to extract result URLs from common field names.
      const resultUrls: Record<string, string> = {};
      if (parsed && typeof parsed === "object") {
        for (const [k, v] of Object.entries(parsed)) {
          if (typeof v === "string" && /^https?:\/\//i.test(v)) {
            resultUrls[k] = v;
          }
        }
        if (parsed.results && typeof parsed.results === "object") {
          for (const [k, v] of Object.entries(parsed.results)) {
            if (typeof v === "string" && /^https?:\/\//i.test(v)) {
              resultUrls[k] = v;
            }
          }
        }
      }
      return {
        ok: true as const,
        payload: text,
        result: parsed,
        resultUrls,
      };
    } catch (err) {
      console.error("Failed to call simulation service:", err);
      return { ok: false as const, error: "Could not reach the simulation service" };
    }
  });
