"""The demo video's inputs stay in step with the code it films (``demo/README.md``).

The video replays recorded answers, keyed by the prompt, schema, OCR text and
model: a change to any of them silently leaves the demo with nothing to replay.
These tests fail first, naming the re-recording, instead of a broken video.
"""

import io
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from demo import render, show_result
from scripts.extract_document import main

DEMO = Path("demo")
SETUP = DEMO / "setup.tape"


def test_the_demo_receipt_replays_with_every_field_cited_but_the_currency(
    no_doc_intake_env: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The settings the tape exports and the recording was made with: stated
    # here too, so a .env that picks another model cannot change the key.
    monkeypatch.setenv("DOC_INTAKE_PROVIDER", "claude")
    monkeypatch.setenv("DOC_INTAKE_CLAUDE_MODEL", "claude-opus-5-5")
    code = main(["--replay", str(DEMO / "recordings"), str(DEMO / "receipt.png")])

    captured = capsys.readouterr()
    assert code == 0, captured.err
    result = json.loads(captured.out)
    assert result["status"] == "ok"
    fields = result["fields"]
    # No currency is printed on the receipt: null with a reason, never a guess.
    assert fields["currency"]["value"] is None
    assert fields["currency"]["reason"]
    for name in ("company", "address", "date", "total"):
        assert fields[name]["citation"]["source"] == "text", name


def test_the_regression_patch_still_applies() -> None:
    git = shutil.which("git")
    assert git is not None, "git is needed to check demo/regression.patch"

    # A fixed argument list with no shell and no outside input.
    checked = subprocess.run(  # noqa: S603
        [git, "apply", "--check", str(DEMO / "regression.patch")],
        capture_output=True,
        text=True,
        check=False,
    )

    assert checked.returncode == 0, checked.stderr


def test_the_result_is_shown_one_line_per_field_with_its_evidence(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    result: dict[str, object] = {
        "status": "ok",
        "fields": {
            "total": {
                "value": "23.40",
                "citation": {"page": 1, "source": "text", "quote": "TOTAL 23.40"},
                "reason": None,
            },
            "currency": {"value": None, "citation": None, "reason": "no currency is printed"},
        },
        "errors": [],
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(result)))

    show_result.main()

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "status: ok"
    assert lines[1].split() == ["total", "23.40", "<-", "page", "1", "text:", '"TOTAL', '23.40"']
    assert lines[2].split() == ["currency", "null", "<-", "no", "currency", "is", "printed"]


def _tapes() -> list[Path]:
    shots = render.shot_tapes(render.SHOTS)
    assert shots, f"no shot tapes in {render.SHOTS}"
    return [SETUP, *shots]


def test_every_wait_in_the_tapes_names_the_state_it_expects() -> None:
    # A bare Wait waits for VHS's default prompt (">"), not for the state a
    # shot needs: a shot that goes wrong would be filmed instead of stopping.
    for tape in _tapes():
        for number, line in enumerate(tape.read_text(encoding="utf-8").splitlines(), 1):
            if line.startswith("Wait"):
                assert re.fullmatch(r"Wait(\+Screen|\+Line)?(@\d+m?s)? /.+/", line), (
                    f"{tape}:{number}: {line}"
                )


def test_every_shot_starts_from_the_shared_setup_with_one_caption() -> None:
    for tape in _tapes()[1:]:
        lines = tape.read_text(encoding="utf-8").splitlines()
        assert f"Source {SETUP.as_posix()}" in lines, tape
        # The render names each shot's output: an Output here would be ignored.
        assert not any(line.startswith("Output") for line in lines), tape
        assert render.caption(tape)


def test_a_caption_is_the_one_caption_line_of_its_tape(tmp_path: Path) -> None:
    tape = tmp_path / "1-scan.tape"
    tape.write_text('# Caption: A faded scan goes in.\nType "clear"\n', encoding="utf-8")

    assert render.caption(tape) == "A faded scan goes in."


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ('Type "clear"\n', "no caption"),
        ("# Caption: One.\n# Caption: Two.\n", "2 captions"),
        ("# Caption: {bold} text\n", "ASS markup"),
    ],
)
def test_a_tape_without_exactly_one_plain_caption_is_refused(
    tmp_path: Path, text: str, problem: str
) -> None:
    tape = tmp_path / "1-scan.tape"
    tape.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match=problem):
        render.caption(tape)


def test_shots_are_rendered_in_the_order_their_names_start_with(tmp_path: Path) -> None:
    for name in ("10-close.tape", "2-fields.tape", "1-scan.tape", "notes.md"):
        (tmp_path / name).write_text("", encoding="utf-8")

    assert [tape.name for tape in render.shot_tapes(tmp_path)] == [
        "1-scan.tape",
        "2-fields.tape",
        "10-close.tape",
    ]


def test_the_caption_is_shown_for_the_whole_shot_in_the_band_below_the_terminal() -> None:
    script = render.ass_script("A faded scan goes in.")

    assert f"PlayResX: {render.WIDTH}" in script.splitlines()
    assert f"PlayResY: {render.HEIGHT}" in script.splitlines()
    dialogue = [line for line in script.splitlines() if line.startswith("Dialogue:")]
    assert dialogue == ["Dialogue: 0,0:00:00.00,9:59:59.99,Caption,,0,0,0,,A faded scan goes in."]


@pytest.mark.parametrize(
    ("seconds", "size", "problem"),
    [
        (60.1, 1_000_000, "60.1 s, above the 60 s"),
        (59.0, 10_000_001, "10000001 bytes, above the 10000000"),
    ],
)
def test_a_video_over_the_limits_is_refused(seconds: float, size: int, problem: str) -> None:
    with pytest.raises(ValueError, match=problem):
        render.check_limits(seconds, size)


def test_a_video_at_the_limits_is_accepted() -> None:
    render.check_limits(60.0, 10_000_000)


def test_the_terminal_leaves_the_caption_band_free_below_it() -> None:
    lines = SETUP.read_text(encoding="utf-8").splitlines()

    assert f"Set Width {render.WIDTH}" in lines
    assert f"Set Height {render.TERMINAL_HEIGHT}" in lines
    assert render.TERMINAL_HEIGHT < render.HEIGHT


def test_a_shot_tape_without_a_number_is_refused(tmp_path: Path) -> None:
    (tmp_path / "scan.tape").write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match=r"<number>-<name>\.tape: \['scan\.tape'\]"):
        render.shot_tapes(tmp_path)


def test_a_shot_may_show_an_image_over_the_terminal(tmp_path: Path) -> None:
    tape = tmp_path / "1-scan.tape"
    tape.write_text("# Caption: In.\n# Image: demo/receipt.png\n", encoding="utf-8")
    plain = tmp_path / "2-fields.tape"
    plain.write_text("# Caption: Out.\n", encoding="utf-8")

    assert render.image(tape) == Path("demo/receipt.png")
    assert render.image(plain) is None


def test_the_image_is_drawn_over_the_terminal_and_the_caption_below_it() -> None:
    subtitle = Path(".cache/demo/shots/1-scan.ass")

    assert render.video_filter(subtitle, image=False) == (
        f"[0:v]pad={render.WIDTH}:{render.HEIGHT}:0:0:color={render.BAND_COLOR},"
        f"ass={subtitle.as_posix()}"
    )
    with_image = render.video_filter(subtitle, image=True)
    assert with_image.startswith(f"[0:v]pad={render.WIDTH}:{render.HEIGHT}")
    assert f"[1:v]scale=-1:{render.IMAGE_HEIGHT}[image]" in with_image
    assert with_image.endswith(
        f"overlay=(W-w)/2:({render.TERMINAL_HEIGHT}-h)/2,ass={subtitle.as_posix()}"
    )


def test_every_image_a_shot_shows_exists() -> None:
    for tape in render.shot_tapes(render.SHOTS):
        shown = render.image(tape)
        assert shown is None or shown.is_file(), f"{tape}: {shown}"
