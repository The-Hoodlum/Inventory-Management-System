# syntax=docker/dockerfile:1
# ---------- build the static SPA ----------
FROM node:20-alpine AS build
WORKDIR /app

# Install deps first for better layer caching.
COPY package.json package-lock.json* ./
RUN npm ci

COPY . .
# The API base URL is baked in at build time (Vite inlines VITE_* env). In production
# the SPA and API are same-origin behind nginx, so this defaults to a relative /api/v1.
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

# ---------- serve with nginx ----------
FROM nginx:1.27-alpine AS serve
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget -qO- http://localhost/healthz >/dev/null 2>&1 || exit 1
CMD ["nginx", "-g", "daemon off;"]
