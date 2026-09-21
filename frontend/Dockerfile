# Static file only — no build step (plain HTML/CSS/JS on purpose, see frontend/README.md).
FROM nginx:1.27-alpine
LABEL org.opencontainers.image.title="nusatel-care-web" \
      org.opencontainers.image.description="Customer-facing chat UI for the NusaTel CS agent"

COPY index.html /usr/share/nginx/html/index.html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1:80/ >/dev/null || exit 1
