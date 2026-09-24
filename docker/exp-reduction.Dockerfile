FROM python:3.12-slim-bookworm

ARG PYDANTIC_VERSION=2.13.5
ARG GIT_COMMIT=unknown
ARG GIT_DIRTY=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app
RUN groupadd --system --gid 10001 stage \
    && useradd --uid 10001 --gid stage --home-dir /app --no-create-home --shell /usr/sbin/nologin stage \
    && mkdir -p /work \
    && chown stage:stage /work \
    && python -m pip install --no-cache-dir "pydantic==${PYDANTIC_VERSION}"

COPY src/fdm_strength/__init__.py /app/src/fdm_strength/__init__.py
COPY src/fdm_strength/baseline.py /app/src/fdm_strength/baseline.py
COPY src/fdm_strength/gui_analysis.py /app/src/fdm_strength/gui_analysis.py
COPY src/fdm_strength/replicates.py /app/src/fdm_strength/replicates.py
COPY src/fdm_strength/study_models.py /app/src/fdm_strength/study_models.py
COPY src/fdm_strength/experimental_reduction.py /app/src/fdm_strength/experimental_reduction.py
COPY src/fdm_strength/exp_reduction_stage.py /app/src/fdm_strength/exp_reduction_stage.py
COPY src/fdm_strength/stage_contract.py /app/src/fdm_strength/stage_contract.py

LABEL org.opencontainers.image.revision=${GIT_COMMIT} \
      fdm.git.commit=${GIT_COMMIT} \
      fdm.git.dirty=${GIT_DIRTY}

USER stage
WORKDIR /work
CMD ["python", "-m", "fdm_strength.exp_reduction_stage"]
