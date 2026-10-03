# syntax=docker/dockerfile:1
# Static web app behind nginx; nginx also forwards /v1 to the API with the proxy secret.
# Build from apps/web: docker build apps/web
FROM node:22-bookworm-slim AS build
WORKDIR /web
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM nginxinc/nginx-unprivileged:1.28-alpine
ENV SEQUENCE_VAULT_API_UPSTREAM=api:8000
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 8080
