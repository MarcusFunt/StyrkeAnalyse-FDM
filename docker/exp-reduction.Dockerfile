FROM python:3.12-slim-bookworm

ARG FDM_DEPENDENCY_LOCK_SHA256
ARG GIT_COMMIT=unknown
ARG GIT_DIRTY=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:${PATH}

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.12.15 /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv venv --python /usr/local/bin/python /opt/venv \
    && uv sync --frozen --only-group exp-reduction --no-install-project \
    && lock_sha256="$(sha256sum uv.lock | cut -d ' ' -f 1)" \
    && test -n "${FDM_DEPENDENCY_LOCK_SHA256}" \
    && test "${lock_sha256}" = "${FDM_DEPENDENCY_LOCK_SHA256}"

COPY src/fdm_strength/__init__.py /app/src/fdm_strength/__init__.py
COPY src/fdm_strength/baseline.py /app/src/fdm_strength/baseline.py
COPY src/fdm_strength/gui_analysis.py /app/src/fdm_strength/gui_analysis.py
COPY src/fdm_strength/replicates.py /app/src/fdm_strength/replicates.py
COPY src/fdm_strength/study_models.py /app/src/fdm_strength/study_models.py
COPY src/fdm_strength/experimental_reduction.py /app/src/fdm_strength/experimental_reduction.py
COPY src/fdm_strength/exp_reduction_stage.py /app/src/fdm_strength/exp_reduction_stage.py
COPY src/fdm_strength/provenance.py /app/src/fdm_strength/provenance.py
COPY src/fdm_strength/stage_contract.py /app/src/fdm_strength/stage_contract.py

RUN groupadd --system --gid 10001 stage \
    && useradd --uid 10001 --gid stage --home-dir /app --no-create-home --shell /usr/sbin/nologin stage \
    && mkdir -p /work \
    && chown stage:stage /work

LABEL org.opencontainers.image.revision=${GIT_COMMIT} \
      fdm.git.commit=${GIT_COMMIT} \
      fdm.git.dirty=${GIT_DIRTY} \
      fdm.base-image.reference=python:3.12-slim-bookworm \
      fdm.dependency-lock.sha256=${FDM_DEPENDENCY_LOCK_SHA256}

USER stage
WORKDIR /work
CMD ["python", "-m", "fdm_strength.exp_reduction_stage"]
