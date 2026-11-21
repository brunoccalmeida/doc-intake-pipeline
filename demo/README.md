# Demo video

A 48-second video of the pipeline for prospective clients, rendered as code. Every frame is drawn with Pillow from the pipeline's own output, replayed from recorded answers. Rendering needs no API key and costs nothing, and the video cannot show a value the pipeline did not produce. Captions are burned in, so it works with the sound off.

| Shot | Seconds | On screen | Caption's point |
| --- | --- | --- | --- |
| 1 | 6 | A faded receipt beside an empty form | The problem: receipts typed in by hand |
| 2 | 10 | The form fills in field by field; each value's words light up on the receipt | Every value comes with the words it was read from |
| 3 | 6 | Currency: "Not on the receipt", with the reason | An empty field, never a guess |
| 4 | 10 | A second receipt with a faded total: that value is marked for a person ([`receipt-review.png`](receipt-review.png)) | What can't be confirmed goes to a person |
| 5 | 10 | Today against a harmless-looking update ([`regression.py`](regression.py)), then "Not shipped" | Every update is re-tested; a worse one never ships |
| 6 | 6 | Closing line | Send a sample |

[`storyboard.py`](storyboard.py) holds the shots and their captions. [`evidence.py`](evidence.py) gathers what they show. [`render.py`](render.py) turns them into the video.

## Render

You need Docker and the same local data as the eval: `uv run poe fetch-tessdata`, `uv run poe fetch-golden` and the clone of the private recordings repository ([`docs/DATA.md`](../docs/DATA.md)).

```sh
uv run poe demo
```

The command builds the image in [`Dockerfile`](Dockerfile), which holds this project's locked environment plus ffmpeg, and runs `render.py` in it:

1. It replays both receipts and finds each quote's words with OCR's own word boxes.
2. It replays the eval with and without the regression.
3. It draws every frame and holds each still for its duration.
4. It joins the clips into `.cache/demo/doc-intake-demo.mp4`.

The render prints each shot's length. It fails if the video runs over 60 s or 10 MB, or if a recording is missing. The working tree is never touched, because the regression changes the prompt in memory.

Check the result by its frames as well, not only by a green render. The stills are in `.cache/demo/frames`.

## What it replays

| Shots | Recording | Where |
| --- | --- | --- |
| 1-3 | Claude's answer for `receipt.png` | [`recordings/`](recordings), public: the receipt is ours |
| 4 | Claude's answer for `receipt-review.png` | [`recordings/`](recordings), public |
| 5 | The 20 answers to the regressed prompt, and the eval's own | Private recordings repository (they quote SROIE); the video shows counts only |

Every recording is keyed by the prompt, schema, OCR text, page image and model (`evals/recording.py`). A change to any of them leaves the demo with nothing to replay. [`tests/test_demo.py`](../tests/test_demo.py) fails first for shots 1 to 4, and for a regression whose anchor is no longer in the prompt. Only a render catches a missing shot-5 answer.

To record again (paid, run on purpose), use the provider and model the render uses, so no `.env` or shell setting changes the keys:

```sh
export DOC_INTAKE_PROVIDER=claude DOC_INTAKE_CLAUDE_MODEL=claude-opus-5-5
# Shots 1-4 (about US$ 0.02 each)
uv run poe extract --record demo/recordings demo/receipt.png
uv run poe extract --record demo/recordings demo/receipt-review.png
# Shot 5 (about US$ 0.63): add regression.LINE after regression.ANCHOR in
# packs/receipt/__init__.py, record, then undo the edit
uv run poe eval --record
git checkout -- packs/receipt/__init__.py
```

Then commit `demo/recordings`, push the private recordings and update their pin (`evals/recordings.json`).

To change a receipt, edit [`make_receipt.py`](make_receipt.py), run `uv run python -m demo.make_receipt`, and record its answer again. The PNGs are committed rather than regenerated, since another Pillow version could change a pixel, and with it the recording key. A test checks that the generator still draws them.

## Decisions (#45)

**Why the video was redone.** The #39 video was a terminal screencast (VHS). Its screen was full of commands, `git diff` and eval reports, and a client could not follow it. This one keeps what that video got right: rendered as code, replayed, and checked by tests. It drops the terminal.

**Drawn with Pillow, joined with ffmpeg.** Pillow was already a dependency, so no new one was added (YAGNI). Each still becomes a clip with ffmpeg, and the [concat demuxer](https://ffmpeg.org/ffmpeg-formats.html#concat) joins the clips without re-encoding. The container (Debian with ffmpeg, pinned by digest) gives the same encoder everywhere. Pillow's bundled font gives the same text on Windows and in the container.

**How it is told.** These choices follow the research done for #45:

- **Problem first.** Vendor guidance agrees that viewers decide in the first seconds. That evidence is weak: vendor-reported, with no controlled study.
- **One idea per shot.**
- **Receipt beside its values, with each value's words lit up.** This is backed by research: Mayer's spatial contiguity (9 of 9 tests) and signaling (26 of 28) principles ([Mayer & Fiorella, Cambridge Handbook of Multimedia Learning](https://www.cambridge.org/core/books/cambridge-handbook-of-multimedia-learning/principles-for-reducing-extraneous-processing-in-multimedia-learning/F29A19FCD34C542806F736E0661C05F5)). Those are learning studies, so here they are a guide, not proof.
- **Shots 4 and 5 show the system catching errors.** Research suggests citations raise trust even when they are wrong ([arXiv 2601.14611](https://arxiv.org/html/2601.14611), not yet peer-reviewed). So showing quotes alone would overclaim.

**Captions.** There are at most 2 lines of 42 characters ([Netflix timed text style guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977), which allows up to 20 characters per second for adults). This video holds itself to 15 characters per second, because the viewer also reads the receipt; that limit is our own judgment. Line breaks are balanced and fall at the end of a sentence where they can. Text contrast is at least 4.5:1, per [WCAG 2.2 SC 1.4.3](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html). Tests check all of this, and that no developer term reaches the screen.

**Honest about what exists.** The review shot marks the value for a person. It does not show a review screen, because the project has none. The closing frame carries no link: Upwork's portfolio rules on contact details could not be read (the support site refuses automated reads), and in the README the video already sits on GitHub. Numbers come from the replayed eval, never typed in. A total shows as the pipeline keeps it ("23.4"), with the printed form in its quote (D15).

**Limits, and where it is published.** These are unchanged from #39:

- An Upwork portfolio project takes one MP4 of at most 60 s and 100 MB ([Upwork support](https://support.upwork.com/hc/en-us/articles/4402033684115-Add-Video-to-Your-Project), read in a browser on 2026-11-21).
- A GitHub attachment takes MP4 (H.264 recommended) up to 10 MB on a free plan ([GitHub Docs, attaching files](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/attaching-files)).
- The README embeds the MP4 as an uploaded attachment, not committed: a regenerated binary would grow the history on every render.

**No voice-over, for now.** The muted preview needs the captions anyway. Narration is [#42](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/42).
