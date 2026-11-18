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
| Repository skeleton and CI              | planned |
| Receipt/invoice schema with citations   | planned |
| PDF and image reading (with OCR)        | planned |
| LLM extractor with validation and retry | planned |
| Golden set (SROIE receipts)             | planned |
| Per-field eval gating CI                | planned |
| Run log and cost per document           | planned |

## Data

The first golden set uses receipts from the public ICDAR 2019 SROIE dataset. Licensing and attribution are recorded in `docs/DATA.md`. No client documents are ever stored in this repository.

## License

MIT
