# syntax=docker/dockerfile:1
# Static Hub SPA. Build context is the repository root so apps/shared is visible.
# Leave VITE_REGISTRY_URL unset so the browser talks same-origin /v1.
FROM node:22-bookworm-slim AS build
WORKDIR /src
RUN corepack enable && corepack prepare pnpm@11.10.0 --activate
COPY apps/hub/package.json apps/hub/pnpm-lock.yaml /src/apps/hub/
WORKDIR /src/apps/hub
RUN pnpm install --frozen-lockfile
COPY apps/shared /src/apps/shared
COPY apps/hub /src/apps/hub
RUN pnpm build

FROM nginx:1.27-alpine
COPY apps/hub/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/apps/hub/dist /usr/share/nginx/html
EXPOSE 80
