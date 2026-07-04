# Runtime image for the Next.js frontend, built and deployed via
# frontend/fly.toml. Multi-stage: install deps + build in one stage, copy
# only the `output: "standalone"` server bundle (see next.config.ts) into a
# slim runtime stage.
FROM node:24-slim AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# BACKEND_URL must be available at build time, not just runtime: next.config.ts
# reads process.env.BACKEND_URL at module load, and Next.js bakes the
# rewrites() destination into its routes manifest during `next build` — the
# standalone server never re-reads it live at startup. Fly's fly.toml [env]
# block only sets runtime env vars, so this must come in as a build arg
# (see frontend/fly.toml's [build.args]).
ARG BACKEND_URL
ENV BACKEND_URL=$BACKEND_URL

RUN npm run build

FROM node:24-slim AS runtime

WORKDIR /app
ENV NODE_ENV=production

COPY --from=build /app/public ./public
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static

EXPOSE 3000

CMD ["node", "server.js"]
