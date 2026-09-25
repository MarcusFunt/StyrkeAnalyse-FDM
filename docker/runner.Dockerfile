FROM python:3.12-slim-bookworm

ARG PYDANTIC_VERSION=2.13.5
ARG DOCKER_SDK_VERSION=7.1.0
ARG GIT_COMMIT=unknown
ARG GIT_DIRTY=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    FDM_RUNNER_HOST=0.0.0.0 \
    FDM_RUNNER_PORT=8020 \
    FDM_RUNNER_DATA_DIR=/data

WORKDIR /app
RUN groupadd --system --gid 10001 runner \
    && useradd --uid 10001 --gid runner --home-dir /app --no-create-home --shell /usr/sbin/nologin runner \
    && mkdir -p /data \
    && chown runner:runner /data \
    && python -m pip install --no-cache-dir "pydantic==${PYDANTIC_VERSION}" "docker==${DOCKER_SDK_VERSION}"

COPY src/fdm_strength/__init__.py /app/src/fdm_strength/__init__.py
COPY src/fdm_strength/run_models.py /app/src/fdm_strength/run_models.py
COPY src/fdm_strength/run_jobs.py /app/src/fdm_strength/run_jobs.py
COPY src/fdm_strength/run_store.py /app/src/fdm_strength/run_store.py
COPY src/fdm_strength/runner.py /app/src/fdm_strength/runner.py
COPY src/fdm_strength/runner_service.py /app/src/fdm_strength/runner_service.py
COPY src/fdm_strength/study_models.py /app/src/fdm_strength/study_models.py
COPY src/fdm_strength/stage_contract.py /app/src/fdm_strength/stage_contract.py
COPY src/fdm_strength/stage_registry.py /app/src/fdm_strength/stage_registry.py

LABEL org.opencontainers.image.revision=${GIT_COMMIT} \
      fdm.git.commit=${GIT_COMMIT} \
      fdm.git.dirty=${GIT_DIRTY}

USER runner
EXPOSE 8020
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8020/api/health', timeout=2)" || exit 1

CMD ["python", "-m", "fdm_strength.runner"]
