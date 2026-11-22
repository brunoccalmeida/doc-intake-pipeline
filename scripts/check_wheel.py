"""Check a built wheel is what a consumer of the core needs (docs/ARCHITECTURE.md D18).

The delivery kit and client repositories install the wheel, not the
repository, so CI checks the wheel itself: the MIT notice in
``.dist-info/licenses/``, every file of ``src/doc_intake`` (``py.typed`` and
data included), nothing else at the top level, and every module importing
from the install.

Run it from the project root (it reads ``src/`` to know what the wheel must
hold), in an environment that has only the wheel, so ``src/`` cannot mask a
packaging error at import time::

    uv run --isolated --no-project --with dist/<wheel> python -m scripts.check_wheel dist/<wheel>

Exit code 0 = the wheel is complete
Exit code 1 = something is missing or extra (each problem on stderr)
"""

import importlib
import pkgutil
import sys
import zipfile
from collections.abc import Sequence
from pathlib import Path

PACKAGE = "doc_intake"
SOURCE_ROOT = Path("src")


def source_files(root: Path) -> list[str]:
    """Return every file of the package under ``root``, as wheel paths, minus bytecode."""
    return sorted(
        path.relative_to(root).as_posix()
        for path in (root / PACKAGE).rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )


def wheel_problems(names: Sequence[str], expected: Sequence[str]) -> list[str]:
    """Return one message per problem in a wheel's file list."""
    problems: list[str] = []
    dist_info = next((n.split("/")[0] for n in names if ".dist-info/" in n), "<dist-info>")
    if f"{dist_info}/licenses/LICENSE" not in names:
        problems.append(f"no {dist_info}/licenses/LICENSE: MIT requires the notice")
    missing = sorted(set(expected) - set(names))
    if missing:
        problems.append(f"not in the wheel: {', '.join(missing)}")
    others = sorted({n.split("/")[0] for n in names} - {PACKAGE, dist_info})
    if others:
        problems.append(f"top-level entries other than {PACKAGE}: {', '.join(others)}")
    return problems


def import_all() -> list[str]:
    """Import the package and every module under it; return their names."""
    package = importlib.import_module(PACKAGE)
    names = [PACKAGE]
    for module in pkgutil.walk_packages(package.__path__, f"{PACKAGE}."):
        importlib.import_module(module.name)
        names.append(module.name)
    return names


def main(argv: Sequence[str]) -> int:
    """Check the wheel at ``argv[0]`` against ``src/`` and import every module."""
    with zipfile.ZipFile(argv[0]) as wheel:
        problems = wheel_problems(wheel.namelist(), source_files(SOURCE_ROOT))
    for problem in problems:
        print(f"ERROR: {problem}", file=sys.stderr)
    if problems:
        return 1
    imported = import_all()
    print(f"{argv[0]}: complete; imported {len(imported)} modules")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
