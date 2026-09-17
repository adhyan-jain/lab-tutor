# LabTutor frontend (Next.js)
FROM node:22-alpine AS deps
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --omit=dev --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend ./
# next.config.mjs's rewrites() reads BACKEND_INTERNAL_URL to decide the
# /api/* proxy target -- and `next build` evaluates rewrites() ONCE and
# bakes the result into .next/routes-manifest.json. A value set only at
# `next start` time (a plain runtime env var) is too late: the manifest
# already has zero rewrites baked in by then. It has to be present here,
# at build time, as a real ARG/ENV -- not just at deploy/run time.
ARG BACKEND_INTERNAL_URL
ENV BACKEND_INTERNAL_URL=${BACKEND_INTERNAL_URL}
RUN npm run build
# This repo has no frontend/public directory (no static assets yet) --
# the runtime stage's COPY --from=build /app/public still needs
# something to copy from, or the build fails identically under Docker
# Compose and here. A no-op if a real public/ dir is added later.
RUN mkdir -p public

FROM node:22-alpine AS runtime
ENV NODE_ENV=production
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public
COPY frontend/package.json ./

RUN addgroup -g 10002 labtutor && adduser -D -u 10002 -G labtutor labtutor \
    && chown -R labtutor:labtutor /app
USER labtutor

EXPOSE 3000
CMD ["npm", "run", "start"]
