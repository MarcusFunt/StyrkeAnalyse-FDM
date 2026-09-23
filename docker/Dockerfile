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
    VIRTUAL_ENV=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:${PATH}

# Preserve DOLFINx's base-image module path while importing the mounted project.
ENV PYTHONPATH=/workspaces/styrkeanalyse-fdm/src:${PYTHONPATH}

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
    && existing_uid_user="$(getent passwd "${USER_UID}" | cut -d: -f1 || true)" \
    && if [ -n "${existing_uid_user}" ] && [ "${existing_uid_user}" != "${USERNAME}" ]; then \
        usermod --login "${USERNAME}" --home "/home/${USERNAME}" --move-home "${existing_uid_user}"; \
    elif ! getent passwd "${USERNAME}" >/dev/null; then \
        useradd --uid "${USER_UID}" --gid "${USER_GID}" --create-home --shell /bin/bash "${USERNAME}"; \
    fi \
    && usermod --uid "${USER_UID}" --gid "${USER_GID}" "${USERNAME}"

# Keep the DOLFINx base packages visible inside the project venv. This prevents
# uv from replacing the PETSc/MPI build that matches the DOLFINx base image.
WORKDIR /opt/project
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY docker/jupyter-requirements.txt /tmp/jupyter-requirements.txt
RUN uv venv --system-site-packages --python /dolfinx-env/bin/python /opt/venv \
    && base_site_packages="$(/dolfinx-env/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')" \
    && venv_site_packages="$(/opt/venv/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')" \
    && printf '%s\n' "${base_site_packages}" > "${venv_site_packages}/dolfinx-env.pth" \
    && uv sync --frozen --all-groups \
    && uv pip install --python /opt/venv/bin/python --requirement /tmp/jupyter-requirements.txt \
    && chown -R "${USER_UID}:${USER_GID}" /opt/venv

WORKDIR /workspaces/styrkeanalyse-fdm
USER ${USERNAME}

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash"]
