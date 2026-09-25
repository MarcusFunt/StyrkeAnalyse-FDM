FROM node:22-bookworm-slim AS frontend-build

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    FDM_GUI_HOST=0.0.0.0 \
    FDM_GUI_PORT=8000 \
    FDM_GUI_STATIC_DIR=/app/frontend/dist \
    FDM_GUI_DATA_DIR=/data

WORKDIR /app
RUN groupadd --system --gid 10001 gui \
    && useradd --uid 10001 --gid gui --home-dir /app --no-create-home --shell /usr/sbin/nologin gui \
    && mkdir -p /data \
    && chown gui:gui /data

# Keep aligned with the exact Pydantic version in uv.lock; the GUI uses it to
# validate saved campaign workspaces without installing the solver stack.
ARG PYDANTIC_VERSION=2.13.5
ARG GIT_COMMIT=unknown
ARG GIT_DIRTY=unknown
RUN python -m pip install --no-cache-dir "pydantic==${PYDANTIC_VERSION}"

COPY src/fdm_strength/__init__.py /app/src/fdm_strength/__init__.py
COPY src/fdm_strength/web.py /app/src/fdm_strength/web.py
COPY src/fdm_strength/study_models.py /app/src/fdm_strength/study_models.py
COPY --from=frontend-build /build/dist/ /app/frontend/dist/

LABEL org.opencontainers.image.revision=${GIT_COMMIT} \
      fdm.git.commit=${GIT_COMMIT} \
      fdm.git.dirty=${GIT_DIRTY}

USER gui
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)" || exit 1

CMD ["python", "-m", "fdm_strength.web"]
