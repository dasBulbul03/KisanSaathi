# --- frontend build --------------------------------------------------------
FROM node:22-slim AS build

WORKDIR /app

# Install with the lockfile first so a dependency change, not a source change,
# is what busts this layer.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci

COPY frontend/ ./

# Baked into the bundle at build time, so the API base has to be known now.
# Left empty it defaults to same-origin, which is what the nginx image serves.
ARG VITE_API_BASE_URL=""
ARG VITE_BACKEND_ORIGIN=""
ARG VITE_SHOW_DEMO_ACCOUNTS=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_BACKEND_ORIGIN=$VITE_BACKEND_ORIGIN \
    VITE_SHOW_DEMO_ACCOUNTS=$VITE_SHOW_DEMO_ACCOUNTS

RUN npm run build

# --- runtime ---------------------------------------------------------------
# The unprivileged variant of the same nginx: same parser, same directives, but
# it runs as uid 101 and keeps its pid and temp files in /tmp. Serving a static
# bundle and proxying one upstream needs no root at all.
FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime

COPY --from=build /app/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY frontend/security-headers.conf /etc/nginx/security-headers.conf

# Validate the config at build time, so a syntax error is a failed build rather
# than a container that crash-loops after deploy. This runs as the unprivileged
# user, so the test uses a throwaway main config under /tmp and touches nothing
# in /etc. `backend` is a Compose service name that cannot resolve during a
# build, so the tested copy points at loopback; every other directive, including
# the unprivileged pid and temp paths, is exactly what ships.
RUN mkdir -p /tmp/check/conf.d \
    && sed 's#http://backend:8000#http://127.0.0.1:8000#g' \
           /etc/nginx/conf.d/default.conf > /tmp/check/conf.d/default.conf \
    && printf 'pid /tmp/check/nginx.pid;\nerror_log /dev/stderr;\nevents {}\nhttp { include /tmp/check/conf.d/*.conf; }\n' \
           > /tmp/check/nginx.conf \
    && nginx -t -c /tmp/check/nginx.conf

USER nginx

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8080/ >/dev/null || exit 1

CMD ["nginx", "-g", "daemon off;"]
