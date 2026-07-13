// @lovable.dev/vite-tanstack-config already includes the following — do NOT add them manually
// or the app will break with duplicate plugins:
//   - tanstackStart, viteReact, tailwindcss, tsConfigPaths, cloudflare (build-only),
//     componentTagger (dev-only), VITE_* env injection, @ path alias, React/TanStack dedupe,
//     error logger plugins, and sandbox detection (port/host/strictPort).
// You can pass additional config via defineConfig({ vite: { ... } }) if needed.
import { defineConfig } from "@lovable.dev/vite-tanstack-config";

// Outside the Lovable sandbox, `npm run build` skips the Cloudflare/nitro deploy
// plugin entirely (see @lovable.dev/vite-tanstack-config), producing a bare fetch
// handler that nothing can serve. Docker builds set DOCKER_BUILD=1 to opt into
// Nitro's node-server preset, which emits a self-hosting Node server instead.
export default defineConfig(
  process.env.DOCKER_BUILD === "1" ? { nitro: { preset: "node-server" } } : {},
);
