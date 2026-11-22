# doc-intake-pipeline

Reads receipts (scanned or photographed images, or PDFs) and returns their key fields as structured data, with every value pointing to where it was found, and anything it is unsure of flagged for a person instead of guessed.

<!-- A bare attachment link is what GitHub renders as a video player (demo/README.md). -->
<!-- markdownlint-disable-next-line MD034 -->
https://github.com/user-attachments/assets/5a2a885b-c432-41f5-ae04-1bede3496aca

## What you get

For each document, a JSON result with company, address, date, total and currency, where:

- **Nothing is made up.** A field the document does not show comes back empty, with the reason.
- **Every value can be checked.** It carries the page and the exact text it was read from.
- **Doubtful values go to a person.** The result names the fields to check; everything else was accepted automatically.
- **A broken answer never passes as a good one.** It is retried a few times, then marked as failed for review, never returned half-filled.
- **The cost of each document is logged**, with no document content in the logs.
- **It is not tied to one AI vendor.** Claude or OpenAI, chosen by a setting.

## How it runs day to day

1. **Documents land in a folder.** Save them there, or use a folder that Google Drive or Dropbox keeps in sync on the computer that runs the pipeline.
2. **The folder is checked on a schedule**, every 15 minutes in the example setup. A file still being copied or synced is left for the next check.
3. **Each check leaves a spreadsheet** that opens in Excel or Google Sheets: one row per field, with the value, the page and the exact text it was read from. Filter `field_status` to `needs_review` and you have the review queue. The original documents are moved into the same folder as the spreadsheet, so each one is next to its rows.
4. **No document is lost.** One that cannot be read is listed as failed. One that hit a temporary problem (network, AI provider) stays in the folder and is tried again on the next check.

Two sample receipts, one of them with a value to check, give this review queue:

| file | field | field_status | value | quote | note |
| --- | --- | --- | --- | --- | --- |
| receipt-review.png | total | needs_review | 10 | TOTAL 10.00 | read from the image of page 1; check it on the page |

The other nine rows (both receipts' remaining fields) are `accepted`. To see it yourself, run `uv run poe inbox-demo` (no API key, no cost).

## How well it works

<!-- eval-summary:start (written by `uv run poe eval --update-readme`) -->
Measured on 20 public scanned receipts, 100 values in all (company, address, date, total, currency):

- **97 of 100 correct.**
- **70 accepted automatically**, none of them wrong.
- **25 sent to a person to check**, 3 of them wrong.
- **5 left empty**, with the reason.
- **$0.63 for the whole set**, about $0.03 per receipt.
<!-- eval-summary:end -->

A wrong value should be caught by review, not reach you unchecked, so every change to the code is re-measured on these receipts and blocked if it gets more answers wrong or accepts a wrong value without review. Evidence: the full report of every run is in the eval job summary of the [CI runs on `main`](https://github.com/brunoccalmeida/doc-intake-pipeline/actions/workflows/ci.yml?query=branch%3Amain); how values are scored is in [How it is measured](docs/DEVELOPMENT.md#eval).

## What it does not do yet

- **Receipts only.** Another document type (invoices, IDs, forms) means a new field list and a new test set of that type, measured the same way.
- **The numbers above come from public receipts** of one country and period (Malaysia, 2016 to 2018). They show the pipeline does not get worse; they do not predict accuracy on your documents, which would be measured on a sample of them ([known limitations](docs/DATA.md#known-limitations)).
- **English text only**, for now.
- **Review happens in the spreadsheet.** There is no review screen yet, and a correction made in the sheet is not sent back to the pipeline.
- **A folder in, a spreadsheet out.** Email inboxes and business systems (QuickBooks, NetSuite and the like) are connected per project; that code is not in this public repository. There is no web API or user interface yet.

## For developers

Setup, commands, configuration, the eval and the data: [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md). Design decisions and their alternatives: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## License

MIT
