import { Outlet, Link, createRootRoute, HeadContent, Scripts, redirect } from "@tanstack/react-router";
import { createIsomorphicFn } from "@tanstack/react-start";
import { getRequestHost } from "@tanstack/react-start/server";
import { useEffect } from "react";
import { seedScenariosFromBackend } from "@/lib/scenarios-store";
import { loadUsersFromBackend } from "@/lib/users-store";
import { getToken, clearToken } from "@/lib/auth";
import { getMeApi } from "@/lib/api";

import appCss from "../styles.css?url";

// The browser reaches the frontend and backend at the same host, on two
// different fixed ports (NodePorts in K8s, host-mapped ports in
// docker-compose) — so the backend URL can be derived from whatever
// hostname the browser used to reach THIS request, instead of hardcoding
// an environment-specific IP anywhere. BACKEND_PORT is the only thing that
// needs to be set (Helm values / docker-compose), and it's just a number.
const resolveApiBaseUrl = createIsomorphicFn()
  .server((): string => {
    try {
      const host = getRequestHost().split(":")[0];
      const port = process.env.BACKEND_PORT;
      if (host && port) return `http://${host}:${port}`;
    } catch {
      // Not inside a request context (shouldn't happen during SSR, but
      // don't take the app down over it).
    }
    return "";
  })
  .client((): string => "");

function NotFoundComponent() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="max-w-md text-center">
        <h1 className="text-7xl font-bold text-foreground">404</h1>
        <h2 className="mt-4 text-xl font-semibold text-foreground">Page not found</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          The page you're looking for doesn't exist or has been moved.
        </p>
        <div className="mt-6">
          <Link
            to="/"
            className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Go home
          </Link>
        </div>
      </div>
    </div>
  );
}

export const Route = createRootRoute({
  // Redirect unauthenticated users to the login page for every route except
  // "/" itself.  Only enforced client-side: localStorage is unavailable during
  // SSR, so we skip the check on the server to avoid spurious redirects on
  // every page refresh.
  beforeLoad: ({ location }) => {
    if (typeof window === "undefined") return; // SSR — no localStorage
    const isLoginPage = location.pathname === "/" || location.pathname === "";
    if (!isLoginPage && !getToken()) {
      throw redirect({ to: "/" });
    }
  },
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      { name: "viewport", content: "width=device-width, initial-scale=1" },
      { title: "DT Lab" },
      { name: "description", content: "Digital Twin Laboratory for Distribution Networks" },
    ],
    links: [
      {
        rel: "stylesheet",
        href: appCss,
      },
    ],
    // Server-rendered on every request (guarded so the browser bundle never
    // touches `process`/`getRequestHost`) — see resolveApiBaseUrl() above
    // and src/lib/api.ts's `window.__RUNTIME_CONFIG__` read.
    scripts:
      typeof window === "undefined"
        ? [
            {
              children: `window.__RUNTIME_CONFIG__ = ${JSON.stringify({
                apiBaseUrl: resolveApiBaseUrl(),
              })};`,
            },
          ]
        : [],
  }),
  shellComponent: RootShell,
  component: RootComponent,
  notFoundComponent: NotFoundComponent,
});

function RootShell({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <HeadContent />
      </head>
      <body>
        {children}
        <Scripts />
      </body>
    </html>
  );
}

function RootComponent() {
  useEffect(() => {
    function bootstrap() {
      const token = getToken();
      if (!token) return;
      // Validate JWT; clear if expired/revoked
      getMeApi().catch(() => clearToken());
      // Seed stores that require auth (admin-only endpoints will 403 for
      // non-admin users — stores handle that gracefully)
      seedScenariosFromBackend();
      loadUsersFromBackend();
    }

    bootstrap();

    // Re-run after every login / logout so stores always reflect the
    // current user's permissions (e.g. admin can now see all users)
    window.addEventListener("dtlab-auth-change", bootstrap);
    return () => window.removeEventListener("dtlab-auth-change", bootstrap);
  }, []);

  return <Outlet />;
}
