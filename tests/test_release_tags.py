"""Every tag the docs tell people to install is the project's own version (#80).

deploy/README.md pointed at v0.2.0 while pyproject.toml still said 0.1.0, so
the tag did not exist and the guide failed on its first command. CI could
not see it: the deploy smoke test swaps the clone for the commit under test.
Tying the docs to ``project.version`` means a doc can only name the release
the code declares, and bumping the version moves every doc in the same PR.
"""

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]

# (file, pattern capturing the tag a reader is told to install)
INSTALL_TAGS = [
    ("deploy/README.md", r"git clone --branch (\S+) "),
    # The deploy smoke test replaces this exact command; a stale copy fails
    # there only after a push, so it is tied to the version here too.
    (".github/workflows/ci.yml", r"git clone --branch (\S+) "),
    ("docs/DEVELOPMENT.md", r"uv add git\+\S+ --tag (\S+)"),
    ("docs/DEVELOPMENT.md", r'tag = "([^"]+)"'),
]


@pytest.mark.parametrize(("path", "pattern"), INSTALL_TAGS)
def test_docs_install_the_project_version(path: str, pattern: str) -> None:
    tags = set(re.findall(pattern, (ROOT / path).read_text(encoding="utf-8")))

    assert tags == {f"v{VERSION}"}, f"{path} installs {sorted(tags)}, project is {VERSION}"
