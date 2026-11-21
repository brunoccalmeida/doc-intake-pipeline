# doc-intake-pipeline

Reads receipts (scanned or photographed images, or PDFs) and returns their key fields as structured data, with every value pointing to where it was found, and anything it is unsure of flagged for a person instead of guessed.

## See it work

In under a minute: a faded receipt goes in, each value comes out with the text it was read from, a missing currency comes out empty with the reason, and a harmless-looking change that makes the answers worse is blocked before it can ship.

## What you get

For each document, a JSON result with company, address, date, total and currency, where:

- **Nothing is made up.** A field the document does not show comes back empty, with the reason.
- **Every value can be checked.** It carries the page and the exact text it was read from.
- **Doubtful values go to a person.** The result names the fields to check; everything else was accepted automatically.
- **A broken answer never passes as a good one.** It is retried a few times, then marked as failed for review, never returned half-filled.
- **The cost of each document is logged**, with no document content in the logs.
- **It is not tied to one AI vendor.** Claude or OpenAI, chosen by a setting.

## How well it works

<!-- eval-summary:start (written by `uv run poe eval --update-readme`) -->
Measured on 20 public scanned receipts, 100 values in all (company, address, date, total, currency):

- **97 of 100 correct.**
- **70 accepted automatically**, none of them wrong.
- **25 sent to a person to check**, 3 of them wrong.
- **5 left empty**, with the reason.
- **$0.63 for the whole set**, about $0.03 per receipt.
<!-- eval-summary:end -->

A wrong value should be caught by review, not reach you unchecked, so every change to the code is re-measured on these receipts and blocked if it gets more answers wrong or accepts a wrong value without review.

## What it does not do yet

- **Receipts only.** Another document type (invoices, IDs, forms) means a new field list and a new test set of that type, measured the same way.
- **The numbers above are from 20 public receipts** from one country and period (Malaysia, 2016 to 2018). They show the pipeline does not get worse; they do not predict accuracy on your documents, which would be measured on a sample of them.
- **English text only**, for now.
- **A command, not a service.** One file in, one JSON result out; there is no web API or user interface yet.

## For developers

Setup, commands, configuration, the eval and the data: [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md). Design decisions and their alternatives: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## License

MIT
