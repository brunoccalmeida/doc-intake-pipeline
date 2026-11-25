# Development

How the pipeline is built, run, measured and configured. The client-facing overview is the [README](../README.md); design decisions and their alternatives are in [`ARCHITECTURE.md`](ARCHITECTURE.md).

## At a Glance

Eval on 20 SROIE receipts, Claude Opus 5.5, sending each scanned page's image along with its OCR text ([#26](https://github.com/brunoccalmeida/doc-intake-pipeline/issues/26)); the previous column is OCR text alone:

| Field | Correct | Accuracy | OCR text only |
| --- | --- | --- | --- |
| company | 19/20 | 95% | 16/20 |
| address | 19/20 | 95% | 10/20 |
| date | 19/20 | 95% | 17/20 |
| total | 20/20 | 100% | 18/20 |
| currency | 20/20 | 100% | 19/20 |

Both columns were measured at #26 and are kept as that comparison; the current gated values are in [`evals/baseline.json`](../evals/baseline.json). The README's summary (values accepted, sent to review and left empty, and the cost) is written by `uv run poe eval --update-readme`, and the eval fails when it no longer matches the run, so those numbers are not repeated here. A value read from the page image cannot be checked against the text by code, so it goes to human review: a `needs_review` result names the fields to check in `review` ([D16](ARCHITECTURE.md#d16-carga-de-revisão-medida-e-valor-errado-aceito-barrado-no-eval-decidida-na-38); every CI run reports these counts in its eval summary). The numbers are a regression baseline, not a claim about other documents (see [`DATA.md`](DATA.md), known limitations).

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
| Run log and cost per document           | done    |
| Demo video, recorded as code            | done    |
| Scheduled inbox run, CSV review queue   | done    |

## Setup and commands

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
uv run poe eval --update-readme  # rewrite the README's eval summary after the numbers change
uv run poe demo            # render the demo video in Docker (replay: no key, no cost)
uv run poe demo-voice      # speak the demo's new voice-over lines, locally on CPU (no key, no cost)
uv run poe inbox <inbox> <runs>  # one run over an inbox folder (paid API calls; --replay DIR for none)
uv run poe inbox-demo      # that run on the two demo receipts, into .cache/inbox-demo (no key, no cost)
```

Both `extract` and `eval` write one JSON line per document to stderr: run and document ids, status and validation errors, calls, retries, tokens, latency and cost in exact USD, never document content. `extract` identifies the document by the SHA-256 of its bytes, not its file name. `DOC_INTAKE_LOG_LEVEL=WARNING` silences these lines. Example (from the eval replay, so latency is near zero):

```json
{"timestamp":"2026-11-19T17:44:12.387820Z","run_id":"01a1f4e8-8da3-7012-958c-b0c6db001cb1","document_id":"X51006619784","pack":"receipt","provider":"claude","models":["claude-opus-5-5"],"status":"ok","errors":[],"calls":1,"retries":0,"input_tokens":2798,"output_tokens":775,"latency_ms":3,"cost_usd":"0.026692"}
```

A document that fails is logged the same way, with `"status":"failed"` and the error class in `errors` (for example `EmptyDocumentError` when no page yields text).

Each pack's JSON Schema (what the LLM is asked to fill, e.g. [`receipt.schema.json`](../src/doc_intake/packs/receipt/receipt.schema.json)) is committed; a snapshot test fails when a model change alters it, so every schema change is a visible diff in review.

OCR runs on Tesseract bundled in the `tesserocr` wheel, so nothing is installed system-wide; only the English model is fetched (into `.cache/tessdata`, outside Git).

Configuration comes from `DOC_INTAKE_*` environment variables, validated at startup; copy `.env.example` to `.env` for local runs.

For Claude, local runs can sign in through the [`ant` CLI](https://platform.claude.com/docs/en/cli-sdks-libraries/cli/quickstart) instead of storing an API key: run `ant auth login` and set `DOC_INTAKE_ANTHROPIC_PROFILE=default` (or the profile you named). The client then uses that profile's OAuth sign-in only, ignoring any `ANTHROPIC_API_KEY` in the shell; a missing profile fails before the first call. Setting both a key and a profile is rejected at startup. On Windows, `ant` ships as `ant_<version>_windows_amd64.zip` on the [releases page](https://github.com/anthropics/anthropic-cli/releases).

Extraction runs on Claude or OpenAI, chosen by `DOC_INTAKE_PROVIDER`, with each provider's native structured output. The engine (`doc_intake.core`) only knows the `LLMProvider` interface; vendor SDKs are imported in `doc_intake.providers` alone, and a lint rule rejects them anywhere else. An answer that fails schema validation is retried with the errors (`DOC_INTAKE_MAX_RETRIES`, default 2) and then reported as `failed`, never partial; a citation whose quote is not on the page it names turns the result into `needs_review`. Each scanned page is sent with its image; a citation says whether its quote came from the page text or the page image, and a value read from the image, which code cannot check, also turns the result into `needs_review`. A `needs_review` result names those fields in `review`, so a caller routes them without parsing `errors`; every other value was accepted. Fields read as printed (company, address) must sit inside their quote, and an amount must be one of the numbers its quote prints, so a value computed from other amounts goes to review when its quote is from the page text (a quote from the image is written by the model, so it checks nothing there; D23). A pack may declare consistency rules between its fields; the receipt pack declares `amounts_add_up` (net + tax + rounding = total, exactly, when net, tax and total are printed), and a failed rule sends every field it names to review, naming the rule ([D23](ARCHITECTURE.md#d23-regras-de-consistência-por-pacote-decidida-na-66)). Money is an exact decimal written as a JSON string, not reformatted to the currency's minor units: a printed `TOTAL 23.40` may come out as `"23.4"`, with the printed form kept in its quote ([D15](ARCHITECTURE.md#d15-dinheiro-guarda-o-valor-não-a-forma-impressa-decidida-na-33)).

Every pull request must pass the `ci-passed` gate: lint, types, tests, the eval, the wheel check, secret scan, workflow audit and dependency audit.

### Using the core from another project

The core is an installable package, `doc-intake-pipeline`, imported as `doc_intake` (`doc_intake.core`, `doc_intake.packs`, `doc_intake.providers`, `doc_intake.batch`, `doc_intake.review`). It is not on PyPI: another uv project depends on it through a git tag, so an upgrade is a deliberate change to that tag ([D18](ARCHITECTURE.md#d18-fronteira-entre-núcleo-kit-de-entrega-e-código-do-cliente-decidida-na-52)).

```bash
uv add git+https://github.com/brunoccalmeida/doc-intake-pipeline --tag v0.2.0
```

This writes `doc-intake-pipeline = { git = "https://github.com/brunoccalmeida/doc-intake-pipeline", tag = "v0.2.0" }` under `[tool.uv.sources]`, and `uv.lock` records the commit the tag resolved to ([uv: Git dependencies](https://docs.astral.sh/uv/concepts/projects/dependencies/#git)). To upgrade, change the tag and run `uv lock`. The consumer needs Python 3.14 or later. The OCR model is not in the package: set `DOC_INTAKE_TESSDATA_DIR` to a directory holding the `eng.traineddata` of `tessdata_fast` at the commit and SHA-256 pinned in [`scripts/fetch_tessdata.py`](../scripts/fetch_tessdata.py). Another model reads different text, so citations and eval results stop being comparable. The per-document run-log line (ids, status, tokens, cost) goes to the `doc_intake.core.runlog` logger at INFO; Python drops it unless the consumer configures a handler for that logger. The evals, scripts and demo stay in this repository and do not ship.

A release goes in this order, because a published tag never moves: a PR bumps `version` in `pyproject.toml` (with `uv lock`) and every tag the docs install, plus the copy of the clone command in `.github/workflows/ci.yml`, which `tests/test_release_tags.py` keeps equal to that version; after the squash merge, an annotated tag `v<version>` goes on the squash commit. Until the tag is pushed, the clone in [`deploy/README.md`](../deploy/README.md) fails, so the tag follows the merge right away.

## Eval

The eval runs the real pipeline (OCR, LLM extraction, validation) over the golden set and scores every field against the ground truth: exact match after folding case and whitespace, dates and amounts by value, an empty field against a value counted as an error both ways. CI does not call the LLM: it replays provider responses recorded once with a real key, keyed by a hash of provider, model, instructions, page images, prompt and schema, so a changed prompt or model fails until it is re-recorded (and re-scored). Replay is deterministic, so the gate has zero tolerance: any field with fewer correct answers than [`evals/baseline.json`](../evals/baseline.json), or with more wrong values accepted without review, fails the build, naming the field. The second count catches what accuracy cannot: a wrong value moving from review to accepted leaves the accuracy unchanged but now reaches a client unchecked. The Markdown report is posted as the job summary and uploaded as an artifact.

A full run that passes the baseline also fails when the README's eval summary (between the `eval-summary` markers) differs from the run; a run below the baseline neither checks nor rewrites it, since the fix is the code and rewriting would publish the worse numbers: after a re-recording or a price change, run `uv run poe eval --update-readme` and commit the README with the new baseline. A run with `--ids` leaves the README alone, since a subset cannot match whole-set numbers.

The recordings quote the receipts, which have no licence, so they live in a private repository pinned by commit ([`DATA.md`](DATA.md)); pull requests from forks cannot run the eval. Design and alternatives: [`ARCHITECTURE.md`](ARCHITECTURE.md) D4.

## Data

The first golden set is 20 receipts from the ICDAR 2019 SROIE dataset, chosen by a reproducible rule. SROIE publishes no licence, so its images and ground truth are not in this repository: `uv run poe fetch-golden` downloads them from a pinned mirror commit, verifies each file's SHA-256 and converts the ground truth locally (into `.cache/golden/sroie`). Source, attribution, selection rule, our currency annotation and known limitations are in [`DATA.md`](DATA.md). No client documents are ever stored in this repository.
