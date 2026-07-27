# Build context is the Frontend/ directory itself, e.g.:
#   docker build -f Frontend/Dockerfile -t dtlab-frontend Frontend
#
# DOCKER_BUILD=1 makes vite.config.ts enable Nitro's node-server preset, which
# produces a self-hosting Node server (dist/server/index.mjs). Without it, the
# Lovable-scaffolded build skips the deploy plugin and emits a bare fetch
# handler that nothing can serve — see Frontend/vite.config.ts for details.

FROM node:22-slim AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
ENV DOCKER_BUILD=1
RUN npm run build

FROM node:22-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/dist ./dist

EXPOSE 3000
# BACKEND_PORT is read live on every SSR request (see src/routes/__root.tsx),
# not baked in at build time — set it per-deployment, e.g. via Helm values.
CMD ["node", "dist/server/index.mjs"]
