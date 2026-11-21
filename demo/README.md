# Demo video

A 40-second sales video for the buyers of this service: business owners and office or operations staff who type receipts in by hand. It is rendered as code. Every frame is drawn with Pillow from the pipeline's own output, replayed from recorded answers. Rendering needs no API key and costs nothing, and the video cannot show a value the pipeline did not produce. The headline on each shot carries the message, so the video works with the sound off.

| Shot | Seconds | On screen | Headline |
| --- | --- | --- | --- |
| 1 | 5 | The receipt already done: every field filled in | Still typing receipts by hand? There's a faster way. |
| 2 | 5 | A pile of fictional receipts | Every week, someone retypes all of these. |
| 3 | 10 | The fields fill in one by one; each value's words are highlighted on the receipt | Vendor, date, total: filled in, each with the words it came from. |
| 4 | 6 | Currency: "Not on the receipt", with the reason | Not on the receipt? Left empty, never guessed. |
| 5 | 8 | A second receipt with a faded total, flagged "A person checks" ([`receipt-review.png`](receipt-review.png)) | Too faint to be sure? Flagged for a person to check. |
| 6 | 6 | Both receipts and a "Send me a sample" button | Your documents, your spreadsheet. Send me a sample. |

[`storyboard.py`](storyboard.py) holds the shots and their headlines. [`evidence.py`](evidence.py) gathers what they show. [`render.py`](render.py) turns them into the video.

## Render

You need Docker and the OCR model (`uv run poe fetch-tessdata`).

```sh
uv run poe demo
```

The command builds the image in [`Dockerfile`](Dockerfile), which holds this project's locked environment plus ffmpeg, and runs `render.py` in it:

1. It replays both receipts and finds each quote's words with OCR's own word boxes.
2. It draws every frame and saves the stills to `.cache/demo/frames`, so they can be checked by eye.
3. It streams the frames to ffmpeg, each held for its duration. Frames within a shot dissolve into each other. Between shots, the picture dips to the background, so two headlines never overlap.
4. It writes `.cache/demo/doc-intake-demo.mp4`.

The render prints each shot's length, and fails if the video runs over 60 s or 10 MB, or if a recording is missing. Check the stills and the video, not only the green render.

## What it replays

Both receipts are answered by Claude and the answers are recorded in [`recordings/`](recordings). They are public, because the receipts are ours. Every recording is keyed by the prompt, schema, OCR text, page image and model (`evals/recording.py`). A change to any of them leaves the demo with nothing to replay, and [`tests/test_demo.py`](../tests/test_demo.py) fails first.

To record again (paid, run on purpose), use the provider and model the render uses, so no `.env` or shell setting changes the keys:

```sh
export DOC_INTAKE_PROVIDER=claude DOC_INTAKE_CLAUDE_MODEL=claude-opus-5-5
uv run poe extract --record demo/recordings demo/receipt.png          # about US$ 0.02
uv run poe extract --record demo/recordings demo/receipt-review.png   # about US$ 0.02
```

Then commit `demo/recordings`.

To change a receipt, edit [`make_receipt.py`](make_receipt.py), run `uv run python -m demo.make_receipt`, and record its answer again. The PNGs are committed rather than regenerated, since another Pillow version could change a pixel, and with it the recording key. A test checks that the generator still draws them. The pile in shot 2 is drawn on the fly: the pipeline never reads it, so it has no recording.

## Decisions (#45)

**Written for the buyer, not for developers.** The #39 video was a terminal screencast, and a client could not follow it. A first redo still had a shot on the eval gate ("a change that makes answers worse is blocked"). The owner cut it: that sells engineering practice to programmers, not an outcome to a client. The video now shows what the buyer gets, and nothing about how it is built. Testing and evaluation stay in the README and [`DEVELOPMENT.md`](../docs/DEVELOPMENT.md).

**Nothing it does not do.** A second research pass proposed a spreadsheet filling in, a clickable value and a review queue. The project has none of these, so the video does not show them:

- The flagged value carries the label "A person checks", and no review screen is shown.
- "Your spreadsheet" appears only in the call to action. Connecting the result to the client's own tools is part of the service.
- The hook says only that there is a faster way than typing; no amount of time saved is claimed, because none was measured.
- A total shows as the pipeline keeps it ("23.4"), with the printed form beside it (D15).

**How it is told.** These choices follow the research for #45. Where the evidence is weak, it is marked.

- **The outcome first.** Google's ABCD guidance for video ads says to "front-load your story arc". The research read that guidance in search snippets, because its pages refused automated reads. Upwork's cover preview plays only the first seconds. So shot 1 is the receipt already done.
- **The problem next, then one idea per shot.**
- **Short.** Nielsen Norman Group: "Typically, Web videos should be less than a minute long" ([NN/g](https://www.nngroup.com/articles/talking-head-video-is-boring-online/)).
- **The receipt beside its values, with each value's words highlighted.** This follows Mayer's spatial contiguity and signaling principles ([Mayer & Fiorella](https://www.cambridge.org/core/books/cambridge-handbook-of-multimedia-learning/principles-for-reducing-extraneous-processing-in-multimedia-learning/F29A19FCD34C542806F736E0661C05F5)). Those are learning studies, so here they are a guide only.
- **The look is our own judgment:** a light palette with one brand colour, paper with soft shadows, a highlighter, and one call-to-action button. The research found no study on these.

**Headlines.** There are at most 2 lines of 42 characters ([Netflix timed text style guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977)). This video holds itself to 15 characters per second; that limit is our own judgment, because the viewer also reads the receipt. Line breaks fall at the end of a sentence where they can. Text contrast is at least 4.5:1, per [WCAG 2.2 SC 1.4.3](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html). Tests check all of this, and that no developer term ("eval", "update", "ship"...) reaches the screen.

**Drawn with Pillow, encoded with ffmpeg.** Pillow was already a dependency, so no new one was added (YAGNI). Remotion would render React animations, and it is free for teams of up to 3 people ([pricing](https://www.remotion.dev/docs/license/pricing.md)), but it would add a Node toolchain for transitions that ffmpeg handles here. The container is Debian with ffmpeg, pinned by digest, and gives the same encoder everywhere.

**Where it is published, and its limits.**

- An Upwork portfolio project takes one MP4 of at most 60 s and 100 MB ([Upwork support](https://support.upwork.com/hc/en-us/articles/4402033684115-Add-Video-to-Your-Project), read in a browser on 2026-11-21).
- A GitHub attachment takes MP4 (H.264 recommended) up to 10 MB on a free plan ([GitHub Docs](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/attaching-files)).
- The README embeds the MP4 as an uploaded attachment, not committed: a regenerated binary would grow the history.
- The closing frame carries no link or contact. Upwork's rules on contact details in portfolio files could not be read, and in the README the video already sits on GitHub.

**No voice-over, for now.** The muted preview needs the headlines anyway. The research found no study on whether a synthetic voice hurts trust. YouTube asks creators to disclose realistic synthetic content ([YouTube Help](https://support.google.com/youtube/answer/14328491)). Narration is [#42](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/42).
