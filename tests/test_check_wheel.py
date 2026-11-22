"""The wheel check: what a consumer installs carries the licence and only the core."""

import zipfile
from pathlib import Path

from scripts.check_wheel import main, wheel_problems

DIST_INFO = "doc_intake_pipeline-0.1.0.dist-info"
GOOD_WHEEL = [
    "doc_intake/__init__.py",
    "doc_intake/py.typed",
    "doc_intake/core/__init__.py",
    f"{DIST_INFO}/licenses/LICENSE",
    f"{DIST_INFO}/METADATA",
    f"{DIST_INFO}/RECORD",
]


def test_a_wheel_with_the_licence_and_only_the_core_passes() -> None:
    assert wheel_problems(GOOD_WHEEL) == []


def test_a_wheel_without_the_licence_fails() -> None:
    names = [name for name in GOOD_WHEEL if not name.endswith("LICENSE")]
    assert wheel_problems(names) == [f"no {DIST_INFO}/licenses/LICENSE: MIT requires the notice"]


def test_a_wheel_without_the_type_marker_fails() -> None:
    names = [name for name in GOOD_WHEEL if name != "doc_intake/py.typed"]
    assert wheel_problems(names) == ["no doc_intake/py.typed: consumers would lose the types"]


def test_a_wheel_shipping_other_top_level_packages_fails() -> None:
    names = [*GOOD_WHEEL, "evals/__init__.py", "tests/conftest.py"]
    assert wheel_problems(names) == [
        "top-level entries other than doc_intake: evals, tests",
    ]


def test_main_reads_the_wheel_and_exits_1_on_a_problem(tmp_path: Path) -> None:
    wheel = tmp_path / "doc_intake_pipeline-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name in GOOD_WHEEL:
            if not name.endswith("LICENSE"):
                archive.writestr(name, "")
    assert main([str(wheel)]) == 1


def test_main_exits_0_on_a_good_wheel(tmp_path: Path) -> None:
    wheel = tmp_path / "doc_intake_pipeline-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name in GOOD_WHEEL:
            archive.writestr(name, "")
    assert main([str(wheel)]) == 0
