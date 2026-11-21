# Demo video

A 2-3 minute screencast of the pipeline, recorded as code: [`demo.tape`](demo.tape) is a [VHS](https://github.com/charmbracelet/vhs) script, so the video is re-rendered with one command instead of re-recorded by hand. It replays recorded answers: rendering needs no API key and costs nothing.

| Scene | What it shows |
| --- | --- |
| 1 | A faded receipt goes in: a simulated scan, fictional ([`receipt.png`](receipt.png)) |
| 2 | Each field comes out with the quote it was read from; the currency, not printed, comes out null with its reason |
| 3 | The eval on the SROIE golden set: accuracy per field and cost per document |
| 4 | A deliberate regression in the prompt ([`regression.patch`](regression.patch)) is blocked by the eval gate |

The narration script for a voice-over is in [`NARRATION.md`](NARRATION.md).

## Render

Needs Docker, and the same local data as the eval: `uv run poe fetch-tessdata`, `uv run poe fetch-golden` and the clone of the private recordings repository ([`docs/DATA.md`](../docs/DATA.md)).

```sh
uv run poe demo
```

It builds the image in [`Dockerfile`](Dockerfile) (VHS's image plus this project's locked environment) and writes `.cache/demo/doc-intake-demo.mp4`. The tape works on a copy of the repository inside the container, so the regression patch never touches your working tree.

## What it replays

| Scene | Recording | Where |
| --- | --- | --- |
| 2 | Claude's answer for `receipt.png` | [`recordings/`](recordings), public: the receipt is ours |
| 3 | The eval's 20 answers | private recordings repository (they quote SROIE) |
| 4 | The 20 answers to the patched prompt | private recordings repository, next to the eval's |

Every recording is keyed by the prompt, schema, OCR text, page image and model (`evals/recording.py`). A change to any of them leaves the demo with nothing to replay; [`tests/test_demo.py`](../tests/test_demo.py) fails first for scene 2 and for a patch that no longer applies.

To record again (paid, run on purpose), with the provider and model the tape exports, so no `.env` or shell setting changes the keys:

```sh
export DOC_INTAKE_PROVIDER=claude DOC_INTAKE_CLAUDE_MODEL=claude-opus-5-5
# Scene 2 (~US$ 0.03)
uv run poe extract --record demo/recordings demo/receipt.png
# Scene 4 (~US$ 0.63): record the patched prompt, then undo the patch
git apply demo/regression.patch
uv run poe eval --record
git checkout -- packs/receipt/__init__.py
```

Then commit `demo/recordings`, push the private recordings and update their pin (`evals/recordings.json`).

To change the receipt, edit [`make_receipt.py`](make_receipt.py), run `uv run python -m demo.make_receipt` and record scene 2 again. The PNG is committed rather than regenerated, since another Pillow version could change a pixel, and with it the recording key.
