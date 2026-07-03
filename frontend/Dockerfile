# Runtime image for the Next.js frontend, built and deployed via
# frontend/fly.toml. Multi-stage: install deps + build in one stage, copy
# only the `output: "standalone"` server bundle (see next.config.ts) into a
# slim runtime stage.
FROM node:24-slim AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM node:24-slim AS runtime

WORKDIR /app
ENV NODE_ENV=production

COPY --from=build /app/public ./public
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static

EXPOSE 3000

CMD ["node", "server.js"]
