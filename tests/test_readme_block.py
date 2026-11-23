"""The README's shell blocks, extracted for CI to run as written (#61)."""

import re
from pathlib import Path

import pytest

from scripts.readme_block import DriftError, main, section_blocks, substitute

README = """\
# Title

## Install

```bash
echo one
echo two
```

Check it:

```bash
echo three
```

```cron
* * * * * not shell
```

### Notes

```bash
echo inside a subsection
```

## Other

```bash
echo other section
```
"""


class TestSectionBlocks:
    def test_returns_the_section_blocks_in_order_with_their_subsections(self) -> None:
        assert section_blocks(README, "## Install") == [
            "echo one\necho two\n",
            "echo three\n",
            "echo inside a subsection\n",
        ]

    def test_stops_at_the_next_heading_of_the_same_level(self) -> None:
        assert section_blocks(README, "## Other") == ["echo other section\n"]

    def test_a_missing_heading_is_drift(self) -> None:
        with pytest.raises(DriftError, match="## Setup"):
            section_blocks(README, "## Setup")

    def test_a_section_without_a_block_is_drift(self) -> None:
        with pytest.raises(DriftError, match="no ```bash block"):
            section_blocks("## Install\n\nprose only\n", "## Install")

    def test_an_unclosed_fence_is_drift(self) -> None:
        with pytest.raises(DriftError, match="unclosed"):
            section_blocks("## Install\n\n```bash\necho one\n", "## Install")


class TestSubstitute:
    def test_replaces_each_declared_text(self) -> None:
        script = "clone tag\nedit .env\nrun\n"
        replaced = substitute(script, [("clone tag", "clone here"), ("edit .env", "write key")])
        assert replaced == "clone here\nwrite key\nrun\n"

    def test_a_text_no_longer_in_the_readme_is_drift(self) -> None:
        with pytest.raises(DriftError, match=re.escape("'sudoedit .env' found 0 times")):
            substitute("run\n", [("sudoedit .env", "write key")])

    def test_a_text_found_twice_is_ambiguous(self) -> None:
        with pytest.raises(DriftError, match="'run' found 2 times"):
            substitute("run\nrun\n", [("run", "go")])


class TestMain:
    def test_prints_a_strict_script(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        readme = tmp_path / "README.md"
        readme.write_text(README, encoding="utf-8")

        code = main([str(readme), "## Other", "--replace", "other", "changed"])

        assert code == 0
        assert capsys.readouterr().out == "set -euxo pipefail\necho changed section\n"

    def test_drift_exits_1_and_names_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        readme = tmp_path / "README.md"
        readme.write_text(README, encoding="utf-8")

        code = main([str(readme), "## Other", "--replace", "missing", "x"])

        assert code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "'missing' found 0 times" in captured.err
