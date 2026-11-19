# doc-intake-pipeline

> **Work in progress.** Week 1 is being built in the open; the numbers below appear as each piece lands on `main`.

A document intake pipeline that reads PDFs and images (including scanned ones), extracts fields with an LLM, and returns a **validated result where every field cites where it came from**. Extraction quality is **measured per field against a golden set**, and CI blocks any change that makes it worse.

## At a Glance

First eval, 20 SROIE receipts, Claude Opus 5.5 ([CI run](https://github.com/brunoccalmeida/doc-intake-pipeline/actions/runs/44561724676)):

| Field | Correct | Accuracy |
| --- | --- | --- |
| company | 15/20 | 75% |
| address | 9/20 | 45% |
| date | 17/20 | 85% |
| total | 18/20 | 90% |
| currency | 17/20 | 85% |

18 calls, 50,903 input and 7,308 output tokens, **$0.35** for the whole set (about 2 cents per receipt). Two receipts fail OCR and count as wrong on every field ([#19](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/19)); most text errors are the model faithfully copying OCR misreadings ([#20](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/20)). The numbers are a regression baseline, not a claim about other documents (see [`docs/DATA.md`](docs/DATA.md), known limitations).

## Why this exists

LLM extraction demos are easy; trusting them in production is not. This project focuses on the part clients actually pay for:

- **No invented values.** A field with no evidence in the document comes back empty, with a reason.
- **Every field is traceable.** Each value carries the page and the exact text it was read from.
- **Malformed output never slips through.** Responses are validated against a schema, retried a bounded number of times, and otherwise flagged for human review.
- **Quality is a number, not a feeling.** Per-field accuracy on a public golden set, reported on every pull request.
- **Cost is visible.** Tokens and cost per document are logged for every run.
- **Provider-agnostic.** Claude or OpenAI behind one interface, selected by configuration.

## Status

| Piece                                   | Status  |
| --------------------------------------- | ------- |
| Repository skeleton and CI              | done    |
| Receipt/invoice schema with citations   | done    |
| PDF and image reading (with OCR)        | done    |
| LLM extractor with validation and retry | done    |
| Golden set (SROIE receipts)             | done    |
| Per-field eval gating CI                | done    |
| Run log and cost per document           | planned |

## Development

Requires [uv](https://docs.astral.sh/uv/) (the version is pinned in `pyproject.toml`); uv installs the pinned Python by itself.

```bash
uv sync              # create .venv from uv.lock
uv run poe fetch-tessdata  # download the pinned, checksum-verified OCR model (needed by the OCR tests)
uv run poe fetch-golden    # download and convert the pinned SROIE golden set (needed by its tests)
uv run poe check     # lint, format check and strict type check
uv run pytest        # tests (no network, no API key)
uv run poe export-schemas  # rewrite the committed JSON Schemas after a schema change
uv run poe extract <file>  # extract one receipt with the configured provider (paid API call)
uv run poe eval            # score the golden set from recorded responses, gate on the baseline
```

Each pack's JSON Schema (what the LLM is asked to fill, e.g. [`packs/receipt/receipt.schema.json`](packs/receipt/receipt.schema.json)) is committed; a snapshot test fails when a model change alters it, so every schema change is a visible diff in review.

OCR runs on Tesseract bundled in the `tesserocr` wheel, so nothing is installed system-wide; only the English model is fetched (into `.cache/tessdata`, outside Git).

Configuration comes from `DOC_INTAKE_*` environment variables, validated at startup; copy `.env.example` to `.env` for local runs.

Extraction runs on Claude or OpenAI, chosen by `DOC_INTAKE_PROVIDER`, with each provider's native structured output. The engine (`core/`) only knows the `LLMProvider` interface; vendor SDKs are imported in `providers/` alone, and a lint rule rejects them anywhere else. An answer that fails schema validation is retried with the errors (`DOC_INTAKE_MAX_RETRIES`, default 2) and then reported as `failed`, never partial; a citation whose quote is not on the page it names turns the result into `needs_review`.

Every pull request must pass the `ci-passed` gate: lint, types, tests, the eval, secret scan, workflow audit and dependency audit.

## Eval

The eval runs the real pipeline (OCR, LLM extraction, validation) over the golden set and scores every field against the ground truth: exact match after folding case and whitespace, dates and amounts by value, an empty field against a value counted as an error both ways. CI does not call the LLM: it replays provider responses recorded once with a real key, keyed by a hash of provider, model, instructions, prompt and schema, so a changed prompt or model fails until it is re-recorded (and re-scored). Replay is deterministic, so the gate has zero tolerance: any field with fewer correct answers than [`evals/baseline.json`](evals/baseline.json) fails the build, naming the field. The Markdown report is posted as the job summary and uploaded as an artifact.

The recordings quote the receipts, which have no licence, so they live in a private repository pinned by commit ([`docs/DATA.md`](docs/DATA.md)); pull requests from forks cannot run the eval. Design and alternatives: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) D4.

## Data

The first golden set is 20 receipts from the ICDAR 2019 SROIE dataset, chosen by a reproducible rule. SROIE publishes no licence, so its images and ground truth are not in this repository: `uv run poe fetch-golden` downloads them from a pinned mirror commit, verifies each file's SHA-256 and converts the ground truth locally (into `.cache/golden/sroie`). Source, attribution, selection rule, our currency annotation and known limitations are in [`docs/DATA.md`](docs/DATA.md). No client documents are ever stored in this repository.

## License

MIT
