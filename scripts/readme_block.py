#!/usr/bin/env python3
"""Print the ```bash blocks of a README section as one script, for CI to run.

The deploy smoke test (#61) runs the install steps of ``deploy/README.md``
themselves, not a copy that could drift from them. A CI machine differs from
a client's in a few declared places (the checkout to install, a dummy API key
instead of an editor), each passed as ``--replace OLD NEW``: OLD must appear
exactly once, so a README edit that removes or duplicates it fails the job
instead of running something nobody reviewed.

Runs on the runner's system Python before uv is installed, so it uses the
standard library only.

Usage: readme_block.py README HEADING [--replace OLD NEW]...

Exit code 0 = the script is on stdout, starting with ``set -euxo pipefail``
Exit code 1 = the README no longer matches (missing heading, block or text)
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

LANGUAGE = "bash"
FENCE = "```"


class DriftError(ValueError):
    """The README no longer matches what the CI job expects of it."""


def _level(line: str) -> int:
    """The level of a Markdown ATX heading (``## X`` is 2), or 0 for other lines."""
    marks = len(line) - len(line.lstrip("#"))
    return marks if marks and line[marks : marks + 1] == " " else 0


def section_blocks(markdown: str, heading: str) -> list[str]:
    """The code of each ```bash block under ``heading``, subsections included.

    The section ends at the next heading of the same or a higher level.
    """
    lines = markdown.splitlines(keepends=True)
    level = _level(heading)
    try:
        start = next(i for i, line in enumerate(lines) if line.rstrip("\n") == heading)
    except StopIteration:
        raise DriftError(f"heading {heading!r} not found") from None

    blocks: list[str] = []
    block: list[str] | None = None
    for line in lines[start + 1 :]:
        text = line.rstrip("\n")
        if block is not None:
            if text == FENCE:
                blocks.append("".join(block))
                block = None
            else:
                block.append(line)
        elif text == FENCE + LANGUAGE:
            block = []
        elif 0 < _level(text) <= level:
            break
    if block is not None:
        raise DriftError(f"unclosed {FENCE}{LANGUAGE} block under {heading!r}")
    if not blocks:
        raise DriftError(f"no {FENCE}{LANGUAGE} block under {heading!r}")
    return blocks


def substitute(script: str, replacements: Sequence[tuple[str, str]]) -> str:
    """Replace each OLD with NEW; OLD must appear exactly once."""
    for old, new in replacements:
        count = script.count(old)
        if count != 1:
            raise DriftError(f"{old!r} found {count} times, expected once")
        script = script.replace(old, new)
    return script


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("readme", type=Path)
    parser.add_argument("heading", help='the section, as written: "## Install"')
    parser.add_argument(
        "--replace",
        nargs=2,
        action="append",
        default=[],
        metavar=("OLD", "NEW"),
        help="a declared difference from the README; OLD must appear once",
    )
    args = parser.parse_args(argv)
    readme: Path = args.readme
    heading: str = args.heading
    replacements: list[tuple[str, str]] = [(old, new) for old, new in args.replace]

    try:
        blocks = section_blocks(readme.read_text(encoding="utf-8"), heading)
        script = substitute("".join(blocks), replacements)
    except DriftError as error:
        print(f"ERROR: {readme}: {error}", file=sys.stderr)
        return 1
    # -x echoes each command into the job log, so a failure names its step.
    print("set -euxo pipefail\n" + script, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
