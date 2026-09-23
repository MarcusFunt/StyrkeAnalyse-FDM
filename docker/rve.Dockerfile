FROM python:3.10-slim-bookworm

ARG USERNAME=fdm
ARG USER_UID=1000
ARG USER_GID=${USER_UID}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspaces/styrkeanalyse-fdm/src

RUN if ! getent group "${USER_GID}" >/dev/null; then groupadd --gid "${USER_GID}" "${USERNAME}"; fi \
    && useradd --uid "${USER_UID}" --gid "${USER_GID}" --create-home --shell /bin/bash "${USERNAME}"

COPY docker/jupyter-requirements.txt /tmp/jupyter-requirements.txt
RUN python -m pip install --no-cache-dir --requirement /tmp/jupyter-requirements.txt \
    && mkdir -p /workspaces/styrkeanalyse-fdm \
    && chown -R "${USER_UID}:${USER_GID}" /workspaces/styrkeanalyse-fdm

WORKDIR /workspaces/styrkeanalyse-fdm
USER ${USERNAME}
