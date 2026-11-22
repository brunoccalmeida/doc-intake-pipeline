"""Check a built wheel is what a consumer of the core needs (docs/ARCHITECTURE.md D18).

The delivery kit and client repositories install the wheel, not the
repository, so CI checks the wheel itself: the MIT notice in
``.dist-info/licenses/``, the ``py.typed`` marker, nothing but ``doc_intake``
at the top level, and the public modules importing from the install.

Run it in an environment that has only the wheel, outside the project, so
``src/`` cannot mask a packaging error::

    uv run --isolated --no-project --with dist/<wheel> python -m scripts.check_wheel dist/<wheel>

Exit code 0 = the wheel is complete
Exit code 1 = something is missing or extra (each problem on stderr)
"""

import importlib
import sys
import zipfile
from collections.abc import Sequence

PACKAGE = "doc_intake"
# What a consumer imports: the engine, the provider factory and each pack.
PUBLIC_MODULES = (
    "doc_intake.core.extract",
    "doc_intake.core.ingest",
    "doc_intake.providers",
    "doc_intake.packs.receipt",
)


def wheel_problems(names: Sequence[str]) -> list[str]:
    """Return one message per problem in a wheel's file list."""
    problems: list[str] = []
    dist_info = next((n.split("/")[0] for n in names if ".dist-info/" in n), "<dist-info>")
    if f"{dist_info}/licenses/LICENSE" not in names:
        problems.append(f"no {dist_info}/licenses/LICENSE: MIT requires the notice")
    if f"{PACKAGE}/py.typed" not in names:
        problems.append(f"no {PACKAGE}/py.typed: consumers would lose the types")
    others = sorted({n.split("/")[0] for n in names} - {PACKAGE, dist_info})
    if others:
        problems.append(f"top-level entries other than {PACKAGE}: {', '.join(others)}")
    return problems


def main(argv: Sequence[str]) -> int:
    """Check the wheel at ``argv[0]`` and import the public modules."""
    with zipfile.ZipFile(argv[0]) as wheel:
        problems = wheel_problems(wheel.namelist())
    for problem in problems:
        print(f"ERROR: {problem}", file=sys.stderr)
    if problems:
        return 1
    for module in PUBLIC_MODULES:
        importlib.import_module(module)
    print(f"{argv[0]}: complete; imported {', '.join(PUBLIC_MODULES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
