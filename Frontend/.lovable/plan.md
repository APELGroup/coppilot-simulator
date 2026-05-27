## Goal

Replace the hardcoded mock networks in the Network Library with real SimBench LV networks fetched from an external Python service. Only metadata is loaded for now; topology, simulation, and results endpoints are reserved for later.

## Backend contract (your Python service)

The service will eventually expose four endpoints, but **only the first is consumed now**:


| Method | Path                     | Purpose                                            | Used now? |
| ------ | ------------------------ | -------------------------------------------------- | --------- |
| GET    | `/networks`              | List of pure LV SimBench networks (metadata only)  | ✅         |
| GET    | `/networks/{id}`         | Full topology of one network                       | later     |
| POST   | `/networks/{id}/run`     | Trigger pandapower/SimBench time-series simulation | later     |
| GET    | `/networks/{id}/results` | Simulation results, plots, summary                 | later     |


`GET /networks` **response shape** (matches your script output):

```json
[
  {
    "id": "1-LV-rural1--0-sw",
    "name": "SimBench 1-LV-rural1--0-sw",
    "voltage": "0.4 kV",
    "type": "LV",
    "status": "validated",
    "created": "2026-04-30",
    "version": "v1.0",
    "buses": 15,
    "lines": 14,
    "transformers": 1,
    "loads": 13
  }
]
```

The frontend `Network` type uses `status: "validated" | "draft" | "archived"` and also has `created` and `version`. The server function will normalize incoming entries:

- `status: "available"` → `"validated"`
- `created` → today's date if missing
- `version` → `"v1.0"` if missing

## Architecture

```text
Browser
   │  navigate to /networks
   ▼
TanStack route loader  ──►  fetchSimbenchNetworks() (createServerFn)
                                   │
                                   ▼
                       fetch(`${SIMBENCH_SERVICE_URL}/networks`)
                                   │
                                   ▼
                       Your Python service (FastAPI/Flask)
```

- Server-side fetch via `createServerFn` keeps `SIMBENCH_SERVICE_URL` out of the client bundle.
- Single fetch on page load; SWR cache handles re-navigation.
- No UI/styling changes to the table, filters, search, or detail page.

## Steps

1. **Add the runtime secret** `SIMBENCH_SERVICE_URL` (stub for now — empty until you deploy the Python service). When unset, the loader returns an empty list with a friendly empty state instead of crashing.
2. **Create server modules:**
  - `src/server/networks.server.ts` — Zod schema for the API response, fetch helper, normalization to the `Network` shape.
  - `src/server/networks.functions.ts` — exports `fetchSimbenchNetworks` via `createServerFn({ method: "GET" })`. Reads `process.env.SIMBENCH_SERVICE_URL` inside the handler. Returns `{ networks: Network[]; error: string | null }` (no throws — graceful empty state on misconfig/network failure).
3. **Wire the loader in** `src/routes/networks.index.tsx`**:**
  - Add `loader: () => fetchSimbenchNetworks()`.
  - Add `errorComponent` (Retry button calling `router.invalidate()`) and `notFoundComponent`.
  - Replace `useNetworks()` with `Route.useLoaderData()`.
  - Keep filter `useState` (UI-only).
  - When list is empty + error present → show "Couldn't reach SimBench service" message.
  - When list is empty + no error → "Configure `SIMBENCH_SERVICE_URL` to load SimBench networks".
4. **Refactor** `src/lib/networks-store.ts`**:**
  - Convert from "wraps the mock array" to "in-memory cache seeded by the loader".
  - Add `seedNetworks(list)` called from the Network Library on mount so other pages (detail page, conversion tools) can still look up by id.
  - Keep `addConvertedNetwork` working — it adds to the cache instead of the mock array.
5. **Update consumers of the deleted mock array:**
  - `src/routes/networks.$networkId.tsx` — replace `networks.find(...)` in `head` and `loader` with a store lookup; if not found in cache, return `notFound()` (acceptable for now since detail topology is a future endpoint).
  - Any other importers of `networks` from `mock-data.ts` (scenarios, conversion-tools, runs-store) — switch to the store.
6. **Remove mocks:** delete the `networks` array export from `src/lib/mock-data.ts`. Keep the `Network` type.
7. **No changes to:** Comparison page, Conversion Tools UI, Results, Users, Auth, navigation, styling.

## Technical details

- **Files created:** `src/server/networks.server.ts`, `src/server/networks.functions.ts`.
- **Files edited:** `src/routes/networks.index.tsx`, `src/routes/networks.$networkId.tsx`, `src/lib/networks-store.ts`, `src/lib/mock-data.ts`, plus any file currently importing `networks` from `mock-data.ts`.
- **Secret:** `SIMBENCH_SERVICE_URL` (runtime only, no `VITE_` prefix). Optional `SIMBENCH_SERVICE_TOKEN` supported as `Authorization: Bearer …` if set.
- **Validation:** Zod schema rejects malformed entries server-side; bad items are skipped with a console warning rather than failing the whole list.
- **Caching:** TanStack Router default SWR (staleTime 0). Fine for a small list.
- **Error handling:** server function returns typed fallback (`{ networks: [], error }`); no raw provider errors reach the client.

## What you'll do after implementation

1. Deploy a tiny Python web service (FastAPI/Flask) wrapping your `get_simbench_networks()` function as `GET /networks`.
2. Set `SIMBENCH_SERVICE_URL` (e.g. `https://your-service.example.com`) in project secrets.
3. Reload the Network Library — real SimBench LV networks appear.
4. Later, add `/networks/{id}`, `/run`, `/results` to the same service; we'll wire the detail page and simulation flow then.