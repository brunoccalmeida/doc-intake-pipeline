# Data

Every dataset the evals use, where it comes from, under what terms, and exactly what was taken from it. No client document is ever stored in this repository.

## SROIE golden set (receipt pack)

### Source

| | |
| --- | --- |
| Dataset | ICDAR 2019 Robust Reading Challenge on Scanned Receipts OCR and Information Extraction (SROIE) |
| Official source | [RRC portal, SROIE 2019](https://rrc.cvc.uab.es/?ch=13), Downloads section (registration required) |
| Paper | Z. Huang, K. Chen, J. He, X. Bai, D. Karatzas, S. Lu, C. V. Jawahar. *ICDAR2019 Competition on Scanned Receipt OCR and Information Extraction*. ICDAR 2019. [arXiv:2103.10213](https://arxiv.org/abs/2103.10213) |
| Mirror used | [`Losyash/SROIE-datasetv2`](https://github.com/Losyash/SROIE-datasetv2) at commit [`235ba41`](https://github.com/Losyash/SROIE-datasetv2/tree/235ba41db8e7c7dc1437143baadb0882a4446d5c), `test/` split |

### Licence

**No licence is published for the dataset** (checked on 2026-11-19):

- The RRC portal's SROIE pages (overview, downloads, FAQ) state no terms of use; downloading requires a portal account, described as "only meant as an expression of interest".
- The paper is CC BY 4.0, but that covers the article, not the data. It says only that the datasets "will be made available after the event", and that sensitive fields of the receipts were blurred for privacy.
- Mirrors do not settle it: the mirror above declares no licence, and [`zzzDavid/ICDAR-2019-SROIE`](https://github.com/zzzDavid/ICDAR-2019-SROIE)'s MIT licence covers its code, not the receipts. Aggregator licences are often wrong and usually more permissive than the source ([Longpre et al., 2023](https://arxiv.org/abs/2310.16787)).

Without a licence, default copyright applies ([GitHub Docs: licensing a repository](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)). So **neither the images nor SROIE's ground truth, nor anything converted from it, is committed.** The repository holds only our own work:

- [`evals/golden/sroie.json`](../evals/golden/sroie.json): mirror, commit, selection seed, the 20 receipt ids with the SHA-256 of each source file, and our currency annotation;
- [`evals/golden/sroie-test-ids.txt`](../evals/golden/sroie-test-ids.txt): the 347 ids of the mirror's test split, so the selection can be re-run offline;
- the selection and conversion code ([`evals/sroie.py`](../evals/sroie.py), [`scripts/fetch_golden.py`](../scripts/fetch_golden.py)).

`uv run poe fetch-golden` downloads the 20 receipts, rejects any file whose SHA-256 differs from the manifest, and writes the images and the converted golden records to `.cache/golden/sroie` (outside Git). If an official licence allowing redistribution appears, committing the converted records becomes possible; the opposite (removing data from a public history) is not.

**Attribution:** any use of these results cites the paper above.

### Recorded responses (eval)

The eval replays recorded LLM responses (`docs/ARCHITECTURE.md` D4). Each response quotes its receipt (company, address, date, total and the cited lines), so it is derived from SROIE as much as the converted ground truth is, and stays out of this repository for the same reason. The recordings live in the **private** repository `brunoccalmeida/doc-intake-recordings`; this repository pins the commit it replays in [`evals/recordings.json`](../evals/recordings.json), and CI reads it with a read-only deploy key. What is public is only what is ours: per-field scores, outcomes by receipt id and field, tokens and cost (the eval report holds no value from a receipt).

The key covers the OCR text and the JSON Schema, so a dependency update that changes either (Pillow, tesserocr, the `eng` model, Pydantic) also needs a re-recording, even in a Dependabot pull request: the eval job then fails with "no recording".

To re-record after a prompt, schema, model or such dependency change: clone the private repository into `DOC_INTAKE_RECORDINGS_DIR` (default `.cache/recordings`), run `uv run poe eval --record` (paid API calls, only for requests not yet recorded), commit and push there, then update the pin, the baseline and the README's eval summary (`uv run poe eval --update-readme`) in the same pull request. The demo video replays its own public recordings ([`demo/README.md`](../demo/README.md)): the same change needs them recorded again, or the demo has nothing to replay; `tests/test_demo.py` catches it first.

### Why the mirror

The official download needs a logged-in account, so it cannot be fetched by a pinned, scriptable command. Of the public mirrors, `Losyash/SROIE-datasetv2` keeps the original file names (`X51005447841`) and the original `test` split with its ground truth, unmodified. `zzzDavid/ICDAR-2019-SROIE`, the most starred, was not used: it renames the files and rewrites ground truth with its own script, so its records are no longer traceable to SROIE ids.

The commit pins the URL and the checksum pins the bytes: if the mirror changes or disappears, the fetch fails instead of silently changing the eval.

### Selection rule

The 20 ids ranked first by `sha256("sroie-golden-v1:<id>")` over the 347 ids of the test split ([`select`](../evals/sroie.py)). A hash instead of `random.sample`, because Python guarantees a stable sequence across versions only for `random()` ([Notes on reproducibility](https://docs.python.org/3/library/random.html#notes-on-reproducibility)). The seed was fixed before seeing the result, and a test checks that the manifest is exactly the rule's output.

The issue suggested the test split; the train split would serve too, since nothing here is trained.

### Conversion

SROIE annotates `company`, `address`, `date` and `total` as transcribed text. Each becomes a cited field on page 1:

- **value:** `company` and `address` as annotated; `date` read day first (the order printed in Malaysia) as ISO 8601; `total` as an exact `Decimal` without the currency symbol (`RM 96.90` → `96.90`, `$8.20` → `8.20`).
- **citation quote:** SROIE's annotation unchanged. It is the printed text as SROIE transcribed it, which is uppercase even where the receipt is not (`Lot 6, Jalan Batai` → `LOT 6, JALAN BATAI`). The eval (#6) must therefore compare text case-insensitively.

Any date or total format not seen in these 20 receipts fails the conversion, so a new format is looked at instead of guessed.

Issue #5 asked to normalize with "the same functions the pack uses", but the pack has none: the LLM returns ISO dates and decimal totals, and the pack's schema only validates them. So the conversion has its own parsers for SROIE's printed formats ([`parse_date`, `parse_total`](../evals/sroie.py)), and what they produce goes through the same `Receipt` schema as the model's answers, with the same `IsoDate` and `Money` rules. Golden records and extractions are therefore held to one definition of a valid value.

### Currency: our annotation

SROIE does not annotate currency, and the `Receipt` schema requires it. We read it from each image, following the pack's rule (ISO code of the printed symbol; null when none is printed, even if the country suggests one):

| Receipts | Printed | Golden |
| --- | --- | --- |
| 15 | `RM` | `MYR`, quote `RM` |
| X51005444041, X51005719903 | nothing | null: no currency is printed |
| X51005433518, X51007231276, X51007231341 | `$` | null: `$` does not identify one currency |

The `$` case is a judgment: these receipts are Malaysian, so the money is ringgit, but the printed symbol alone does not say so, and the pack forbids inferring from the country.

### Corrections

All 20 records were checked against their image on 2026-11-19. **No correction was needed**: each `company`, `address`, `date` and `total` matches what is printed. A future correction needs the image as evidence and a row here (receipt, field, SROIE value, corrected value, what the image shows).

### Scan quality

Judged by eye, to know what the set covers:

| Quality | Receipts |
| --- | --- |
| Low: faded thermal print | X51006619346, X51006619784 |
| Low: handwriting over the text, broken print | X51006329183 |
| Low: folded corner hiding text | X51008099088 |
| Low: dot-matrix with specks | X51006335818 |
| Small receipt on a full A4 page | X51005433518, X51006414512, X51007231276, X51007231341 |
| Clean | the other 11 |

### Known limitations

- **Contamination:** SROIE, ground truth included, is widely copied across public GitHub and Hugging Face repositories, so current LLMs have likely seen these receipts and their answers. Accuracy measured on this set may be optimistic; publishing test data in plain text is what feeds that ([Jacovi et al., 2023](https://aclanthology.org/2023.emnlp-main.308)). This is one more reason the converted records stay out of Git.
- **Small sample:** 20 receipts from one country and one period (2016-2018) detect regressions; they do not estimate accuracy on other documents.
- **One draw per request:** the recordings hold one answer from a model that does not answer the same way twice. Replay makes the gate deterministic, but a re-recording can move a score by sampling alone, with no change to the pipeline. A drop seen right after a re-recording is checked against a second recording before it is blamed on the change.

## Demo receipts (fictional)

[`demo/receipt.png`](../demo/receipt.png) and [`demo/receipt-review.png`](../demo/receipt-review.png) are drawn by [`demo/make_receipt.py`](../demo/make_receipt.py) with Pillow's bundled font (Aileron, [`ImageFont.load_default`](https://pillow.readthedocs.io/en/stable/reference/ImageFont.html#PIL.ImageFont.load_default)): the shops, addresses and amounts are invented. Being our own work, the images and the recorded answers about them ([`demo/recordings`](../demo/recordings)) are public, released with the code under this repository's licence. The demo video shows only these receipts and a pile of more fictional ones drawn the same way; it shows no SROIE receipt or value.
