# syntax=docker/dockerfile:1.7
#
# Build from the repo root (so .git is in context for LFS):
#   docker build -f frontend/Dockerfile -t sojs-frontend .
# Run:
#   docker run --rm -p 3000:3000 sojs-frontend

# ---------- Stage 1: hydrate Git LFS objects ----------
FROM debian:bookworm-slim AS lfs
RUN apt-get update \
 && apt-get install -y --no-install-recommends git git-lfs ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && git lfs install --system
WORKDIR /repo
# Copy the git metadata + working tree, then materialize LFS pointers into real files.
COPY .git ./.git
COPY .gitattributes ./.gitattributes
COPY frontend ./frontend
RUN git lfs pull --include "frontend/public/*"

# ---------- Stage 2: install deps + build Next.js ----------
FROM oven/bun:1 AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production
COPY --from=lfs /repo/frontend/package.json /repo/frontend/bun.lock ./
RUN bun install --frozen-lockfile
COPY --from=lfs /repo/frontend ./
RUN bun run build

# ---------- Stage 3: minimal runtime ----------
FROM node:22-bookworm-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
RUN groupadd --system --gid 1001 nodejs \
 && useradd  --system --uid 1001 --gid nodejs nextjs

# Next.js standalone output bundles the server + node_modules it actually needs.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
# public/ contains the (now real) LFS files (.ply, splats, audio worklets, etc.)
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
