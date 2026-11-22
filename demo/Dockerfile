# The demo's render environment: this project's Python environment plus ffmpeg,
# so the video is drawn from the pipeline's real output (replayed) and encoded
# the same way on any machine. Built and run by "uv run poe demo"
# (demo/README.md), which runs demo/render.py from the repository mounted at
# /work.

# uv at the version pyproject.toml requires ([tool.uv] required-version).
FROM ghcr.io/astral-sh/uv:0.13.9@sha256:d3b601f0c7b118bc1753febf7c41cc80981df678445e0254284eecf84db79a7d AS uv

FROM debian:trixie-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2

# ffmpeg: encodes the frames demo/render.py streams to it, in one pass.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /usr/local/bin/uv

# The environment lives outside the mounted repository: a .venv built on the
# host (Windows) would not run here, and this one must not overwrite it.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_LINK_MODE=copy

WORKDIR /opt/app
COPY pyproject.toml uv.lock .python-version ./
# Dependencies only: the project itself (src/doc_intake) is not copied into the
# image. "uv run" installs it, editable, from the repository mounted at /work.
# https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
RUN UV_COMPILE_BYTECODE=1 uv sync --locked --no-install-project

WORKDIR /work
