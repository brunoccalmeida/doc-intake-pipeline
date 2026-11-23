"""deploy/README.md installs what the project pins (#61).

The deploy smoke test in CI runs the README's install block, and its
``uv sync`` would refuse a uv other than ``required-version``. These checks
name the drift locally, in seconds, instead of as a failed sync minutes into
a CI job, and keep the download checked against a pinned hash.
"""

import re
import tomllib
from pathlib import Path

from scripts.readme_block import section_blocks

ROOT = Path(__file__).resolve().parent.parent
INSTALL = "".join(
    section_blocks((ROOT / "deploy" / "README.md").read_text(encoding="utf-8"), "## Install")
)


def test_installs_the_uv_version_the_project_requires() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    required = str(pyproject["tool"]["uv"]["required-version"]).removeprefix("==")

    versions = set(re.findall(r"astral-sh/uv/releases/download/([^/]+)/", INSTALL))

    assert versions == {required}


def test_checks_the_uv_download_against_a_pinned_sha256() -> None:
    assert re.search(r"echo \"[0-9a-f]{64}  \S+\" \| sha256sum --check --strict", INSTALL)
