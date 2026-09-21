# syntax=docker/dockerfile:1.7
# The DOLFINx image supplies MPI, PETSc, petsc4py and dolfinx as one tested unit.
ARG DOLFINX_IMAGE=ghcr.io/fenics/dolfinx/dolfinx:stable
FROM ${DOLFINX_IMAGE}

# Copying the uv binary avoids a curl-pipe-shell installer during image builds.
COPY --from=ghcr.io/astral-sh/uv:0.12.15 /uv /uvx /bin/

USER root

ARG USERNAME=fdm
ARG USER_UID=1000
ARG USER_GID=${USER_UID}

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:${PATH}

# CalculiX is an independent reference solver. Gmsh is installed as both a CLI
# and a shared library for the Python API. tini forwards signals correctly to MPI jobs.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        calculix-ccx \
        git \
        gmsh \
        libegl1 \
        libgl1 \
        libxrender1 \
        make \
        openssh-client \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && if ! getent group "${USER_GID}" >/dev/null; then groupadd --gid "${USER_GID}" "${USERNAME}"; fi \
    && useradd --uid "${USER_UID}" --gid "${USER_GID}" --create-home --shell /bin/bash "${USERNAME}"

# Keep DOLFINx's system packages visible inside the project venv. This prevents
# uv from replacing the PETSc/MPI build that matches the DOLFINx base image.
WORKDIR /opt/project
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv venv --system-site-packages --python python3 /opt/venv \
    && uv sync --frozen --all-groups \
    && chown -R "${USER_UID}:${USER_GID}" /opt/venv

WORKDIR /workspaces/styrkeanalyse-fdm
USER ${USERNAME}

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash"]
