# The demo's recording studio: VHS (terminal recorder) plus this project's
# Python environment, so the tape runs the real commands. Built and run by
# "uv run poe demo" (demo/README.md); the repository is mounted at /vhs.

# uv at the version pyproject.toml requires ([tool.uv] required-version).
FROM ghcr.io/astral-sh/uv:0.13.9@sha256:d3b601f0c7b118bc1753febf7c41cc80981df678445e0254284eecf84db79a7d AS uv

# VHS's own image (Debian, with ttyd, ffmpeg and Chromium); its entrypoint is vhs.
FROM ghcr.io/charmbracelet/vhs:v0.12.1@sha256:ea49a6a1c529be83153e88321892b5585964418f0b9055e8c1e0d732194234a3

# git: the tape applies the regression patch. chafa: draws the receipt image
# in the terminal for scene 1.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends git chafa \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /usr/local/bin/uv

# The environment lives outside the mounted repository: a .venv built on the
# host (Windows) would not run here, and this one must not overwrite it.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_LINK_MODE=copy

WORKDIR /opt/app
COPY pyproject.toml uv.lock .python-version ./
# Bytecode compiled once, here: as an ENV, every "uv run" in the video would
# compile it again and print so.
RUN UV_COMPILE_BYTECODE=1 uv sync --locked

WORKDIR /vhs
