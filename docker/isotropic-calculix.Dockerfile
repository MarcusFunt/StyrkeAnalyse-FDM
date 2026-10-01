# syntax=docker/dockerfile:1.7
ARG DOLFINX_IMAGE=ghcr.io/fenics/dolfinx/dolfinx:v0.11.0@sha256:2ae4bfbc0d9077268880faf04c72750528bee986c94ab223a2c159969bd56fa8
ARG GIT_COMMIT=unknown
ARG GIT_DIRTY=unknown
FROM ${DOLFINX_IMAGE}

ARG DOLFINX_IMAGE
ARG GIT_COMMIT
ARG GIT_DIRTY
ENV DEBIAN_FRONTEND=noninteractive

USER root
RUN apt-get update \
    && apt-get install --yes --no-install-recommends calculix-ccx=2.21-1 tini \
    && dpkg-query -W -f='${Version}\n' calculix-ccx > /opt/calculix-version \
    && test -s /opt/calculix-version \
    && command -v ccx \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /work

WORKDIR /work
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["ccx"]

LABEL org.opencontainers.image.revision=${GIT_COMMIT} \
      fdm.git.commit=${GIT_COMMIT} \
      fdm.git.dirty=${GIT_DIRTY} \
      fdm.base-image.reference=${DOLFINX_IMAGE} \
      fdm.solver.name=CalculiX
