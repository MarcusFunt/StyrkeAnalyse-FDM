FROM python:3.12-slim-bookworm

# Install the notebook environment without curl-pipe-shell.
COPY --from=ghcr.io/astral-sh/uv:0.12.15 /uv /uvx /bin/

ARG USERNAME=fdm
ARG USER_UID=1000
ARG USER_GID=${USER_UID}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspaces/styrkeanalyse-fdm/src \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:${PATH}

RUN if ! getent group "${USER_GID}" >/dev/null; then groupadd --gid "${USER_GID}" "${USERNAME}"; fi \
    && useradd --uid "${USER_UID}" --gid "${USER_GID}" --create-home --shell /bin/bash "${USERNAME}"

WORKDIR /opt/project
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY docker/jupyter-requirements.txt /tmp/jupyter-requirements.txt
RUN uv venv --python python3 /opt/venv \
    && uv sync --frozen --all-groups \
    && uv pip install --python /opt/venv/bin/python --requirement /tmp/jupyter-requirements.txt \
    && mkdir -p /workspaces/styrkeanalyse-fdm \
    && chown -R "${USER_UID}:${USER_GID}" /opt/venv /workspaces

WORKDIR /workspaces/styrkeanalyse-fdm
USER ${USERNAME}
