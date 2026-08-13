FROM oven/bun:1 AS build
WORKDIR /app

COPY . .

RUN bun install --frozen-lockfile

# Env validation runs at build time; provide placeholders for required vars
ARG NODE_ENV=production
ARG NEXT_PUBLIC_SITE_URL=http://localhost:3000
ARG UPSTASH_REDIS_REST_URL=http://placeholder:8079
ARG UPSTASH_REDIS_REST_TOKEN=placeholder_token

ENV NODE_ENV=$NODE_ENV
ENV NEXT_PUBLIC_SITE_URL=$NEXT_PUBLIC_SITE_URL
ENV UPSTASH_REDIS_REST_URL=$UPSTASH_REDIS_REST_URL
ENV UPSTASH_REDIS_REST_TOKEN=$UPSTASH_REDIS_REST_TOKEN

RUN bun run build:web

# --- runner stage ---
FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

COPY --from=build /app/apps/web/public ./apps/web/public
COPY --from=build --chown=nextjs:nodejs /app/apps/web/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/apps/web/.next/static ./apps/web/.next/static

# i18n: loadMessages resolves localeDir relative to process.cwd() (/app)
COPY --from=build /app/apps/web/public/locales ./public/locales

USER nextjs

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["node", "apps/web/server.js"]
