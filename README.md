# doc-intake-pipeline

> **Work in progress.** Week 1 is being built in the open; the numbers below appear as each piece lands on `main`.

A document intake pipeline that reads PDFs and images (including scanned ones), extracts fields with an LLM, and returns a **validated result where every field cites where it came from**. Extraction quality is **measured per field against a golden set**, and CI blocks any change that makes it worse.

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
| Per-field eval gating CI                | planned |
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
```

Each pack's JSON Schema (what the LLM is asked to fill, e.g. [`packs/receipt/receipt.schema.json`](packs/receipt/receipt.schema.json)) is committed; a snapshot test fails when a model change alters it, so every schema change is a visible diff in review.

OCR runs on Tesseract bundled in the `tesserocr` wheel, so nothing is installed system-wide; only the English model is fetched (into `.cache/tessdata`, outside Git).

Configuration comes from `DOC_INTAKE_*` environment variables, validated at startup; copy `.env.example` to `.env` for local runs.

Extraction runs on Claude or OpenAI, chosen by `DOC_INTAKE_PROVIDER`, with each provider's native structured output. The engine (`core/`) only knows the `LLMProvider` interface; vendor SDKs are imported in `providers/` alone, and a lint rule rejects them anywhere else. An answer that fails schema validation is retried with the errors (`DOC_INTAKE_MAX_RETRIES`, default 2) and then reported as `failed`, never partial; a citation whose quote is not on the page it names turns the result into `needs_review`.

Every pull request must pass the `ci-passed` gate: lint, types, tests, secret scan, workflow audit and dependency audit.

## Data

The first golden set is 20 receipts from the ICDAR 2019 SROIE dataset, chosen by a reproducible rule. SROIE publishes no licence, so its images and ground truth are not in this repository: `uv run poe fetch-golden` downloads them from a pinned mirror commit, verifies each file's SHA-256 and converts the ground truth locally (into `.cache/golden/sroie`). Source, attribution, selection rule, our currency annotation and known limitations are in [`docs/DATA.md`](docs/DATA.md). No client documents are ever stored in this repository.

## License

MIT
