# Demo video

A 60-second screencast of the pipeline for clients, recorded as code: each shot is a [VHS](https://github.com/charmbracelet/vhs) script in [`shots/`](shots), so the video is re-rendered with one command instead of re-recorded by hand. It replays recorded answers: rendering needs no API key and costs nothing. Captions are burned in, so it works with the sound off.

| Shot | Caption's point |
| --- | --- |
| [1](shots/1-scan.tape) | A faded receipt goes in: a simulated scan, fictional ([`receipt.png`](receipt.png)) |
| [2](shots/2-fields.tape) | Each value found comes out with the quote it was read from |
| [3](shots/3-null.tape) | The currency, not printed, comes out null with its reason |
| [4](shots/4-change.tape) | A deliberate regression in the prompt ([`regression.patch`](regression.patch)) |
| [5](shots/5-gate.tape) | The eval gate blocks it: wrong values that would be accepted without review |
| [6](shots/6-close.tape) | The pull request cannot merge; where the code is |

## Render

Needs Docker, and the same local data as the eval: `uv run poe fetch-tessdata`, `uv run poe fetch-golden` and the clone of the private recordings repository ([`docs/DATA.md`](../docs/DATA.md)).

```sh
uv run poe demo
```

It builds the image in [`Dockerfile`](Dockerfile) (VHS's image plus this project's locked environment) and runs [`render.py`](render.py) in it: each shot is rendered by VHS, its caption burned by ffmpeg in a band below the terminal, and the shots are joined into `.cache/demo/doc-intake-demo.mp4`. The render prints each shot's length and fails if the video runs over 60 s or 10 MB. Every shot works on a fresh copy of the repository inside the container ([`setup.tape`](setup.tape)), so the regression patch never touches your working tree.

To change a caption, edit the shot's `# Caption:` line. To add a shot, name it `<number>-<name>.tape`, start it with `Source demo/setup.tape` and give it one caption; [`tests/test_demo.py`](../tests/test_demo.py) checks both, and that every `Wait` names the state it expects.

## What it replays

| Shots | Recording | Where |
| --- | --- | --- |
| 2, 3 | Claude's answer for `receipt.png` | [`recordings/`](recordings), public: the receipt is ours |
| 5 | The 20 answers to the patched prompt | private recordings repository (they quote SROIE) |

Every recording is keyed by the prompt, schema, OCR text, page image and model (`evals/recording.py`). A change to any of them leaves the demo with nothing to replay; [`tests/test_demo.py`](../tests/test_demo.py) fails first for shots 2 and 3 and for a patch that no longer applies.

To record again (paid, run on purpose), with the provider and model the tapes export, so no `.env` or shell setting changes the keys:

```sh
export DOC_INTAKE_PROVIDER=claude DOC_INTAKE_CLAUDE_MODEL=claude-opus-5-5
# Shots 2 and 3 (~US$ 0.03)
uv run poe extract --record demo/recordings demo/receipt.png
# Shot 5 (~US$ 0.63): record the patched prompt, then undo the patch
git apply demo/regression.patch
uv run poe eval --record
git checkout -- packs/receipt/__init__.py
```

Then commit `demo/recordings`, push the private recordings and update their pin (`evals/recordings.json`).

To change the receipt, edit [`make_receipt.py`](make_receipt.py), run `uv run python -m demo.make_receipt` and record shots 2 and 3 again. The PNG is committed rather than regenerated, since another Pillow version could change a pixel, and with it the recording key.

## Decisions (#39)

**Where it is published, and its limits.** An Upwork portfolio project takes one MP4 of at most 60 seconds and 100 MB, whose cover preview plays muted on hover ([Upwork support](https://support.upwork.com/hc/en-us/articles/4402033684115-Add-Video-to-Your-Project); the page refuses automated reads, so these limits come from a search summary of it). A GitHub attachment takes MP4 (H.264 recommended) up to 10 MB on a free plan ([GitHub Docs, attaching files](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/attaching-files)). The render enforces the stricter pair: 60 s and 10 MB.

**Captions: one per shot, burned in by ffmpeg.** VHS has no caption or overlay command ([README at v0.12.1](https://github.com/charmbracelet/vhs/blob/v0.12.1/README.md), the latest release). Its image's ffmpeg is Debian's 7.1 build, with libass ([`debian/rules`](https://salsa.debian.org/multimedia-team/ffmpeg/-/raw/debian/7%257.1.5-0+deb13u1/debian/rules); `ffmpeg -filters` in the image lists `ass` and `subtitles`), so the [`ass` filter](https://ffmpeg.org/ffmpeg-filters.html#ass) burns each caption over its whole shot and the [concat demuxer](https://ffmpeg.org/ffmpeg-formats.html#concat) joins the shots without re-encoding. A single subtitle file with timestamps was rejected: every timestamp would move whenever a command took longer. `Hide` stops capturing frames ([README](https://github.com/charmbracelet/vhs/blob/v0.12.1/README.md#hide)), so slow commands run off camera and a shot's length is its typing and its `Sleep`s. Each cut is noted in its tape (the eval's run of about 20 s in shot 5); no caption claims how long a command takes.

**No voice-over, for now.** The hover preview plays muted, so captions carry the video. A synthetic narration was researched: [ElevenLabs](https://elevenlabs.io/terms)' free plan is non-commercial; OpenAI's speech models are deprecated, shutting down on 2027-01-06 ([guide](https://developers.openai.com/api/docs/guides/text-to-speech)); hosted voices must be disclosed as AI-generated ([OpenAI](https://developers.openai.com/api/docs/guides/text-to-speech), [Microsoft](https://learn.microsoft.com/en-us/legal/ai-code-of-conduct)); a local model with Apache-2.0 weights ([Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)) fits a video rendered as code but is unproven here (CPU, Docker, timing each clip to its shot). It is left to its own issue.

**One video.** The earlier 2:52 cut, with its narration script, was replaced: it was never published, and two cuts would both need updating on every prompt or report change. The full eval report stays in the repository for anyone who wants the detail.

**In the README: an uploaded attachment.** The MP4 is uploaded to GitHub and its link embedded, rather than committed: the docs above cover uploaded MP4s, not a video committed to the repository, and a regenerated binary would grow the history on every render. A GIF has the same 10 MB limit, blurs terminal text and has no sound.
