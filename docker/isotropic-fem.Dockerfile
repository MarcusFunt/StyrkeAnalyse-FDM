# syntax=docker/dockerfile:1.7
ARG DOLFINX_IMAGE=ghcr.io/fenics/dolfinx/dolfinx:v0.11.0@sha256:2ae4bfbc0d9077268880faf04c72750528bee986c94ab223a2c159969bd56fa8
ARG FDM_DEPENDENCY_LOCK_SHA256
ARG GIT_COMMIT=unknown
ARG GIT_DIRTY=unknown
FROM ${DOLFINX_IMAGE}

COPY --from=ghcr.io/astral-sh/uv:0.12.15@sha256:62f8c047d0a0e9ece6b53fc63df902585a67a47a7f318ddec4a37db586edc8e3 /uv /uvx /bin/

USER root
ARG DOLFINX_IMAGE
ARG FDM_DEPENDENCY_LOCK_SHA256
ARG GIT_COMMIT
ARG GIT_DIRTY

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    HOME=/tmp \
    PATH=/opt/venv/bin:${PATH} \
    PYTHONPATH=/app/src:${PYTHONPATH}

RUN apt-get update \
    && apt-get install --yes --no-install-recommends libgl1 libglu1-mesa tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 stage \
    && useradd --uid 10001 --gid stage --home-dir /app --no-create-home --shell /usr/sbin/nologin stage \
    && mkdir -p /work \
    && chown stage:stage /work

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv venv --system-site-packages --python /dolfinx-env/bin/python /opt/venv \
    && base_site_packages="$(/dolfinx-env/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')" \
    && venv_site_packages="$(/opt/venv/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')" \
    && printf '%s\n' "${base_site_packages}" > "${venv_site_packages}/dolfinx-env.pth" \
    && uv sync --frozen --no-dev \
    && uv pip install --python /opt/venv/bin/python gmsh==4.13.1 \
    && lock_sha256="$(sha256sum uv.lock | cut -d ' ' -f 1)" \
    && test -n "${FDM_DEPENDENCY_LOCK_SHA256}" \
    && test "${lock_sha256}" = "${FDM_DEPENDENCY_LOCK_SHA256}" \
    && printf '%s\n' "${DOLFINX_IMAGE}" | grep -Eq '^ghcr\.io/fenics/dolfinx/dolfinx(:[^@]+)?@sha256:[0-9a-f]{64}$' \
    && /opt/venv/bin/python -c 'import dolfinx, gmsh, petsc4py, ufl' \
    && chown -R 10001:10001 /opt/venv

LABEL org.opencontainers.image.revision=${GIT_COMMIT} \
      fdm.git.commit=${GIT_COMMIT} \
      fdm.git.dirty=${GIT_DIRTY} \
      fdm.base-image.reference=${DOLFINX_IMAGE} \
      fdm.dependency-lock.sha256=${FDM_DEPENDENCY_LOCK_SHA256}

USER stage
WORKDIR /work
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "fdm_strength.isotropic_fem_stage"]
