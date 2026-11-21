"""The demo video tells the story it claims, from the pipeline's real output (``demo/README.md``).

The video replays recorded answers, keyed by the prompt, schema, OCR text and
model: a change to any of them silently leaves the demo with nothing to replay.
These tests fail first, naming the re-recording, instead of a broken video. The
others hold the video to its audience (#45): plain words, captions short enough
to read, the problem in the first shot.
"""

import re
from pathlib import Path

import pytest
from PIL import Image

from core.config import Settings
from core.ingest import ingest
from core.result import Citation, ExtractedField
from demo import evidence, make_receipt, render, storyboard


@pytest.fixture
def demo_settings(no_doc_intake_env: None, monkeypatch: pytest.MonkeyPatch) -> Settings:
    # The provider and model the recordings were made with, stated so that a
    # .env picking another model cannot change the keys.
    monkeypatch.setenv("DOC_INTAKE_PROVIDER", "claude")
    monkeypatch.setenv("DOC_INTAKE_CLAUDE_MODEL", "claude-opus-5-5")
    return Settings()


def test_the_demo_receipt_replays_with_every_field_cited_but_the_currency(
    demo_settings: Settings,
) -> None:
    result = evidence.replayed(make_receipt.RECEIPT.path, demo_settings)

    assert result.status == "ok"
    # No currency is printed on the receipt: null with a reason, never a guess.
    assert result.fields["currency"].value is None
    assert result.fields["currency"].reason
    for name in ("company", "address", "date", "total"):
        citation = result.fields[name].citation
        assert citation is not None, name
        assert citation.source == "text", name


def test_the_review_receipt_replays_with_only_the_faded_total_sent_to_a_person(
    demo_settings: Settings,
) -> None:
    result = evidence.replayed(make_receipt.REVIEW.path, demo_settings)

    assert result.status == "needs_review"
    assert result.review == ["total"]
    citation = result.fields["total"].citation
    assert citation is not None
    assert citation.source == "image"


@pytest.mark.parametrize("receipt", make_receipt.RECEIPTS, ids=lambda receipt: receipt.path.name)
def test_each_committed_receipt_is_what_the_generator_draws(receipt: make_receipt.Receipt) -> None:
    # The PNG is committed, not regenerated (its pixels key the recording); this
    # keeps the generator honest about what it made.
    with Image.open(receipt.path) as committed:
        assert committed.tobytes() == make_receipt.draw_receipt(receipt).tobytes(), (
            f"{receipt.path} is not what demo/make_receipt.py draws (another Pillow or "
            "platform?): run 'uv run python -m demo.make_receipt' and record both "
            "receipts again, about US$ 0.04 (demo/README.md)"
        )


def test_the_faded_total_of_the_review_receipt_is_not_in_the_ocr_text() -> None:
    # Shot 5's premise: OCR loses the faded lines, so the model can read the
    # total only from the image, and an image quote goes to a person (D14).
    text = ingest(make_receipt.REVIEW.path, tessdata_dir=Settings().tessdata_dir).pages[0].text

    assert "TOTAL" not in text
    assert "10.00" not in text
    assert "Banana bread" in text  # the rest of the receipt is still read


def test_a_quote_is_found_on_the_receipt_one_box_per_printed_line() -> None:
    tessdata = Settings().tessdata_dir
    words = evidence.ocr_words(make_receipt.RECEIPT.path, tessdata)

    total = evidence.quote_boxes(words, "TOTAL 23.40")
    address = evidence.quote_boxes(words, "12 Example Street\nSample Town")

    assert len(total) == 1
    left, top, right, bottom = total[0]
    # The TOTAL row is the 12th printed line (demo/make_receipt.py: 60 + 11 * 52).
    assert top < 60 + 11 * 52 + 30 < bottom
    # The word and the amount, not one of them: "TOTAL" and "23.40" both inside.
    for word in ("TOTAL", "23.40"):
        word_box = next(box for text, box in words if text == word)
        assert left <= word_box[0], word
        assert word_box[2] <= right, word
    assert len(address) == 2
    assert address[0][1] < address[1][1]


def test_a_quote_read_only_from_the_image_has_no_box_on_the_page_text() -> None:
    words = evidence.ocr_words(make_receipt.REVIEW.path, Settings().tessdata_dir)

    assert evidence.quote_boxes(words, "TOTAL 10.00") == []


def test_the_real_video_highlights_every_text_quote_and_speaks_plainly(
    demo_settings: Settings,
) -> None:
    # The evidence the render uses (recorded answers, OCR word boxes), not fake
    # values: a re-recorded quote OCR cannot find word for word ("TOTAL 23.4")
    # would leave its field without a highlight, and a reason worded for a
    # developer would reach the screen, both behind a green render.
    receipt = evidence.receipt_evidence(make_receipt.RECEIPT.path, demo_settings)
    review = evidence.receipt_evidence(make_receipt.REVIEW.path, demo_settings)

    for shown in (receipt, review):
        for name, field in shown.result.fields.items():
            if field.citation is not None and field.citation.source == "text":
                assert shown.boxes[name], f"{shown.image.name}: {name} has no highlight"
    for shot in storyboard.storyboard(receipt, review):
        for text in (shot.caption, *(text for frame in shot.frames for text in frame.texts)):
            assert not _DEVELOPER_TERMS.search(text), text


# --- The storyboard, from fake evidence: the story holds whatever the values.


def _field(
    value: str | None, quote: str | None = None, *, image: bool = False
) -> ExtractedField[str]:
    if value is None:
        return ExtractedField[str](value=None, citation=None, reason="Not printed.")
    citation = Citation(page=1, source="image" if image else "text", quote=quote or value)
    return ExtractedField[str](value=value, citation=citation, reason=None)


def _evidence(path: Path, *, review: bool) -> evidence.Evidence:
    fields = {
        "company": _field("SHOP"),
        "address": _field("1 Road\nTown"),
        "date": _field("2026-11-14", "Date: 14/11/2026"),
        "total": _field("23.4", "TOTAL 23.40", image=review),
        "currency": _field(None),
    }
    result = evidence.Shown(
        status="needs_review" if review else "ok",
        fields=fields,
        errors=["total: check it"] if review else [],
        review=["total"] if review else [],
    )
    boxes = {name: [(10, 10, 100, 40)] for name in fields if not (review and name == "total")}
    return evidence.Evidence(image=path, result=result, boxes=boxes)


@pytest.fixture
def shots() -> list[storyboard.Shot]:
    return storyboard.storyboard(
        _evidence(make_receipt.RECEIPT.path, review=False),
        _evidence(make_receipt.REVIEW.path, review=True),
    )


def test_the_video_fits_where_it_is_published(shots: list[storyboard.Shot]) -> None:
    assert sum(shot.seconds for shot in shots) <= render.MAX_SECONDS


def test_the_first_shot_states_the_problem(shots: list[storyboard.Shot]) -> None:
    assert "by hand" in shots[0].caption


def test_the_first_frame_already_shows_the_outcome(shots: list[storyboard.Shot]) -> None:
    # The muted preview plays the first seconds only: the receipt already done
    # (Google's ABCD: front-load the story), not an empty form.
    first = shots[0].frames[0]

    assert first.receipt is not None
    assert {"SHOP", "23.4"} <= set(first.texts)


@pytest.mark.parametrize("index", range(6))
def test_every_caption_is_short_enough_to_read_while_watching(
    shots: list[storyboard.Shot], index: int
) -> None:
    shot = shots[index]
    lines = storyboard.caption_lines(shot.caption)

    # Netflix: at most 2 lines of 42 characters, up to 20 characters per second
    # for adults. The viewer also has to look at the receipt, so the pace here
    # is held to 15 (demo/README.md).
    assert 1 <= len(lines) <= 2, lines
    assert all(len(line) <= 42 for line in lines), lines
    assert len(shot.caption) / shot.seconds <= 15, shot.caption


# Words a client would have to be a developer to read (#45). "Ship" and
# "update" read as software jargon: the first cut's shot 5 was not understood.
_DEVELOPER_TERMS = re.compile(
    r"\b(null|none|json|eval|ci|prompt|ocr|llm|api|schema|baseline|pull request|"
    r"sroie|status|needs_review|regression|patch|diff|git|uv|poe|ship\w*|update)\b",
    re.IGNORECASE,
)


def test_nothing_on_screen_needs_a_developer_to_read_it(shots: list[storyboard.Shot]) -> None:
    for shot in shots:
        for text in (shot.caption, *(text for frame in shot.frames for text in frame.texts)):
            assert not _DEVELOPER_TERMS.search(text), text


def test_the_receipt_and_its_values_are_on_screen_together(shots: list[storyboard.Shot]) -> None:
    # Every frame of the shots about values shows the receipt beside the fields
    # (spatial contiguity), so checking a value needs no memory of the image.
    for shot in (shots[0], *shots[2:5]):
        for frame in shot.frames:
            assert frame.receipt is not None
            assert {"Vendor", "Total"} <= set(frame.texts)


def test_every_frame_fills_the_video(shots: list[storyboard.Shot]) -> None:
    for shot in shots:
        for frame in shot.frames:
            assert frame.image.size == (storyboard.WIDTH, storyboard.HEIGHT)


@pytest.mark.parametrize(
    ("caption", "lines"),
    [
        (
            "Have documents like these? Send me a sample.",
            ["Have documents like these?", "Send me a sample."],
        ),
        (
            "Each value comes with the exact words it was read from.",
            ["Each value comes with the", "exact words it was read from."],
        ),
        ("Short and plain.", ["Short and plain."]),
    ],
)
def test_a_long_caption_breaks_into_balanced_lines_at_a_sentence_if_it_can(
    caption: str, lines: list[str]
) -> None:
    # No word left alone on the second line; a sentence ends a line where it fits.
    assert storyboard.caption_lines(caption) == lines


def test_the_crossfades_keep_the_video_as_long_as_its_frames() -> None:
    ticks = render.timeline([1.0, 0.5], fps=10, fade=0.2)

    assert len(ticks) == 15
    assert ticks[0] == (0, 0, 0.0)
    assert ticks[8] == (0, 0, 0.0)  # 0.8 s: the fade starts after it
    assert ticks[9] == (0, 1, pytest.approx(0.5))  # 0.9 s: halfway into the next frame
    assert ticks[10] == (1, 1, 0.0)  # 1.0 s: the next frame, whole
    assert all(shown == 1 and amount == 0 for shown, _, amount in ticks[10:])  # no fade out


def test_between_shots_the_picture_dips_to_the_background_so_headlines_never_overlap() -> None:
    # The background is off-centre (200), so no wrong formula lands on the expected value by chance.
    black, white = Image.new("RGB", (2, 2), "black"), Image.new("RGB", (2, 2), "white")
    grey = Image.new("RGB", (2, 2), (200, 200, 200))

    halfway = render.dissolve(black, white, 0.5, via=grey)
    assert halfway.tobytes() == grey.tobytes()  # only the background, no mix of the two
    # A quarter in: halfway from the outgoing still (black) to the background
    # (200); three quarters: halfway from the background to the incoming (white).
    for amount, expected in ((0.25, 100), (0.75, 227.5)):
        pixel = render.dissolve(black, white, amount, via=grey).getpixel((0, 0))
        assert isinstance(pixel, tuple)
        assert all(abs(channel - expected) <= 1 for channel in pixel), (amount, pixel)
    # Within a shot (same headline) the frames dissolve straight into each other.
    mixed = render.dissolve(black, white, 0.5).getpixel((0, 0))
    assert isinstance(mixed, tuple)
    assert all(abs(channel - 127.5) <= 1 for channel in mixed)  # half of each


@pytest.mark.parametrize(("foreground", "background"), storyboard.TEXT_ON)
def test_text_contrasts_with_its_background(
    foreground: tuple[int, int, int], background: tuple[int, int, int]
) -> None:
    # WCAG 2.2 SC 1.4.3: at least 4.5:1 for text.
    assert storyboard.contrast(foreground, background) >= 4.5


def test_contrast_follows_the_wcag_formula() -> None:
    assert storyboard.contrast((0, 0, 0), (255, 255, 255)) == pytest.approx(21)
    assert storyboard.contrast((119, 119, 119), (255, 255, 255)) == pytest.approx(4.48, abs=0.01)


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
