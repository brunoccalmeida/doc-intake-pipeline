"""The wheel check: what a consumer installs carries the licence and the whole core."""

import zipfile
from pathlib import Path

from scripts.check_wheel import main, source_files, wheel_problems

DIST_INFO = "doc_intake_pipeline-0.1.0.dist-info"
SOURCE = ["doc_intake/__init__.py", "doc_intake/py.typed", "doc_intake/core/runlog.py"]
GOOD_WHEEL = [
    *SOURCE,
    f"{DIST_INFO}/licenses/LICENSE",
    f"{DIST_INFO}/METADATA",
    f"{DIST_INFO}/RECORD",
]


def test_a_wheel_with_the_licence_and_every_source_file_passes() -> None:
    assert wheel_problems(GOOD_WHEEL, SOURCE) == []


def test_a_wheel_without_the_licence_fails() -> None:
    names = [name for name in GOOD_WHEEL if not name.endswith("LICENSE")]
    assert wheel_problems(names, SOURCE) == [
        f"no {DIST_INFO}/licenses/LICENSE: MIT requires the notice"
    ]


def test_a_wheel_missing_a_source_file_fails() -> None:
    names = [name for name in GOOD_WHEEL if name != "doc_intake/core/runlog.py"]
    assert wheel_problems(names, SOURCE) == ["not in the wheel: doc_intake/core/runlog.py"]


def test_a_wheel_shipping_other_top_level_packages_fails() -> None:
    names = [*GOOD_WHEEL, "evals/__init__.py", "tests/conftest.py"]
    assert wheel_problems(names, SOURCE) == [
        "top-level entries other than doc_intake: evals, tests",
    ]


def test_source_files_lists_the_package_tree_without_bytecode(tmp_path: Path) -> None:
    package = tmp_path / "doc_intake"
    (package / "core" / "__pycache__").mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "py.typed").write_text("")
    (package / "core" / "runlog.py").write_text("")
    (package / "core" / "__pycache__" / "runlog.cpython-314.pyc").write_text("")
    assert source_files(tmp_path) == sorted(SOURCE)


def _write_wheel(path: Path, names: list[str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, "")


def test_main_reads_the_wheel_and_exits_1_on_a_problem(tmp_path: Path) -> None:
    wheel = tmp_path / "doc_intake_pipeline-0.1.0-py3-none-any.whl"
    _write_wheel(wheel, [name for name in GOOD_WHEEL if not name.endswith("LICENSE")])
    assert main([str(wheel)]) == 1


def test_main_exits_0_and_imports_the_package_on_a_complete_wheel(tmp_path: Path) -> None:
    # The real source tree: run from the project root, as the CI job does.
    wheel = tmp_path / "doc_intake_pipeline-0.1.0-py3-none-any.whl"
    _write_wheel(wheel, [*source_files(Path("src")), *GOOD_WHEEL[len(SOURCE) :]])
    assert main([str(wheel)]) == 0
