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

The eval replays recorded LLM responses (`docs/ARCHITECTURE.md` D4). Each response quotes its receipt (company, address, date, the amounts and the cited lines), so it is derived from SROIE as much as the converted ground truth is, and stays out of this repository for the same reason. The recordings live in the **private** repository `brunoccalmeida/doc-intake-recordings`; this repository pins the commit it replays in [`evals/recordings.json`](../evals/recordings.json), and CI reads it with a read-only deploy key. What is public is only what is ours: per-field scores, outcomes by receipt id and field, tokens and cost (the eval report holds no value from a receipt).

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

### Amounts: our annotation, kept private (#66)

SROIE does not annotate the amount before tax, the tax or the rounding adjustment, and the `Receipt` schema requires them since #66 (`docs/ARCHITECTURE.md` D23). We read them from each image on 2026-11-24, following the pack's instructions: an amount is printed, never computed; `net` is a single printed amount before tax (a `Total (Excluding GST)` line or the amount column of a one-rate tax summary); `tax` is the tax added or included; `rounding` is the adjustment line; each is null with a reason when not printed.

Unlike the currency code, these values and their quotes are content of the receipts, so the annotation lives in the **private** recordings repository, at `golden/sroie-amounts.json`, at the pinned commit. `uv run poe fetch-golden` reads it from `DOC_INTAKE_RECORDINGS_DIR` and refuses to run without it, or when it and the manifest name different receipts. The CI `test` job therefore checks out the recordings repository too, with the same read-only deploy key as the `eval` job; a pull request from a fork has no secret and fails there, by design.

What is public is the shape only:

| Receipts | What is printed |
| --- | --- |
| 14 | net, tax and, on 5 of them, a rounding line: the rule applies |
| 4 | the tax only, "included in total" (no amount before tax) |
| 1 | the tax split by rate (6% and 0%), with no single amount before tax |
| 1 | no tax at all (a prepaid fuel chit) |

**Checked against SROIE:** on the 14 receipts where the rule applies, net + tax + rounding equals SROIE's own total exactly, and `tests/test_golden_sroie.py` keeps it so: a misread amount fails there. A mutation (one tax one cent off) failed it. The 6 others have no independent check: one reading from the image, compared with the OCR text where it reads the line.

**Annotated before the model was run:** the golden set and the prompt normally change in separate pull requests, so the expected answer is never fitted to the model's output. New fields need both at once, so this annotation came first instead. It was committed to the recordings repository (`a683792`, 2026-11-24) before the receipts were re-recorded with the new prompt (`6644c45`, 2026-11-25), and `golden/` is unchanged between the two commits.

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

## FATURA golden set (invoice pack, #69)

### Source

| Item | Value |
| --- | --- |
| Dataset | FATURA: a multi-layout invoice image dataset, by Mahmoud Limam, Marwa Dhiaf and Yousri Kessentini |
| Official source | [Zenodo record 10371464](https://zenodo.org/records/10371464), file `FATURA2.zip` (690,717,658 bytes, MD5 `4c9404462f22c5241eb1a290a02eb2a2`, as published with the record) |
| What it holds | 10,000 invoice images generated from 50 templates (200 each), plus the same images on colored backgrounds, with annotations in three formats |
| Used | `images/` (white background) and `Annotations/Original_Format/` |

### Licence

The record's metadata declares **CC BY 4.0**, and its description adds no other terms. The archive itself holds no licence file (checked on 2026-11-27 by listing it). CC BY 4.0 allows reproducing and sharing the material "in whole or in part", commercial use included ([legal code](https://creativecommons.org/licenses/by/4.0/legalcode.en), §2(a)(1)(A)), provided the creators are credited, the licence is linked and changes are indicated (§3(a)). So, unlike SROIE, **the selected images, their converted golden records and the recorded answers about them are committed**: [`evals/golden/fatura`](../evals/golden/fatura) and [`evals/recordings/fatura`](../evals/recordings/fatura), with the attribution in [`evals/golden/fatura/README.md`](../evals/golden/fatura/README.md).

Changes made: none to the images, which are copied byte for byte. The golden records (`<id>.json`) are ours, converted from FATURA's annotations by [`evals/fatura.py`](../evals/fatura.py). The recordings are a model's answers about the images.

### Selection rule

FATURA's second evaluation strategy splits by **template**: `Strat2_Split.txt` lists the templates held out for testing (`test_inds`, the same list as `dev_inds`: the archive has no separate test group). The golden set is instances 0 and 1 of each of those 10 templates (2, 4, 7, 10, 12, 25, 32, 39, 49, 50), 20 invoices in all. The prompt was written from the receipt pack's rules and general invoice practice, and no model answer on these layouts was recorded before it was final. It is not blind to them, though: the images of five (2, 4, 25, 39, 49) were looked at to check the golden records against the page, which is how the buyer was found to be ambiguous (below), and the review of this set led to three instruction changes (a single tax line that names its rate is the tax; a line-item tax column is not; a logo is not the seller's name). Every label the instructions quote also appears on training templates ([D24](ARCHITECTURE.md#d24-pacote-de-faturas-e-suítes-do-eval-decidida-na-69)). Rebuild with `uv run poe build-fatura-golden <path to FATURA2.zip>`; the build checks the MD5 first.

### Conversion

FATURA annotates each object with its printed text, label included (`"TOTAL : 870.74 USD"`). The converter parses the value from that text, and the whole text is the citation (`source: "image"`, page 1). It stops on anything it does not recognize (an unknown label, a second date, a currency it does not know): a guessed golden value would score the pipeline against a wrong answer.

| Field | From | Rule |
| --- | --- | --- |
| `number` | `NUMBER` | Text after the label (`INVOICE #`, `INVOICE ID`, `Invoice number`) |
| `date`, `due_date` | `DATE`, `DUE_DATE` | The one `DD-Mon-YYYY` date in the text |
| `seller_name` | `SELLER_NAME` | As printed |
| `seller_address` | `SELLER_ADDRESS` | After `Address:`, lines joined by a space |
| `subtotal`, `total` | `SUB_TOTAL`, `TOTAL` | The amount closing the text; `TOTAL` is sometimes labeled `BALANCE DUE` |
| `tax` | `TAX`, or a single `GST(n%)` line | Several `GST(n%)` lines and no total tax: `null`, "tax printed only per rate, with no total" (the receipt pack's rule) |
| `currency` | Symbol after the total, subtotal or tax | `USD` or `EUR` as printed; `$` alone is `null` ("several currencies use it", invariant 1); none printed is `null`. FATURA prints no `€` or `£` |

A class the template does not annotate is `null`, "not printed": on the images checked, a field FATURA does not annotate is not printed either (template 19 prints no total; template 39 prints no total and no seller name).

### Known limitations

- **Template-generated:** clean digital renderings, one date format (`DD-Mon-YYYY`), amounts always as `LABEL : value CUR`. Synthetic data tends to overstate accuracy (for example 96.5% on synthetic versus 92.7% on real invoices in [arXiv 2509.04469](https://arxiv.org/html/2509.04469v1), not a controlled comparison). The report's title says so.
- **Amounts do not add up:** where FATURA annotates both, subtotal + tax − discount equals the total on about 1% of invoices; the generator draws them independently. The pack therefore has no sum rule, since this set could not prove one; the receipt pack carries it (D23). Extraction is still scored on the printed values, so a model that "corrects" an amount is scored wrong.
- **Generator artifacts:** due dates before issue dates, the seller's address reused as the buyer's. Both are copied as printed.
- **Left out:** the buyer (template 49 prints a "Bill to" block and a "BILL_TO" block with different names, so not even the golden set can say who the buyer is), discounts, line items, `AMOUNT_DUE` (no held-out template uses it without `TOTAL`; the converter stops on it rather than decide unseen).
- **Small sample:** 20 invoices on 10 layouts detect regressions; they do not estimate accuracy on a client's invoices, which is measured on the client's reviewed documents (D21).

## Datasets checked for calibrating auto-acceptance (#35, not used)

Issue #35 looked for a public labeled receipt set of a few hundred documents to calibrate per-field auto-acceptance (`docs/ARCHITECTURE.md` D14). None qualifies, so **no file was added** and none of these is fetched. Checked on 2026-11-22; a licence counts only when the dataset owner states it at the source, since aggregator licences are often wrong ([Longpre et al., 2023](https://arxiv.org/abs/2310.16787)).

| Dataset | Licence at the source | Fields of our schema labeled | Verdict |
| --- | --- | --- | --- |
| [CORD v2](https://github.com/clovaai/cord) (Clova AI) | **CC BY 4.0**: `LICENSE-CC-BY` in the owner's repository, and `license: cc-by-4.0` on the owner's [Hugging Face card](https://huggingface.co/datasets/naver-clova-ix/cord-v2) (not gated) | `total` only: the owner removed `store_info`, `payment_info` and `etc` from the 1,000 published receipts (800 train, 100 dev, 100 test) "due to Indonesian legal issues" | Licence fine, but no `company`, `address`, `date` or `currency`. Indonesian receipts in rupiah |
| [WildReceipt](https://github.com/open-mmlab/mmocr/blob/main/docs/en/user_guides/data_prepare/kie.md) (OpenMMLab) | None: the docs and the [paper](https://arxiv.org/abs/2103.14470) state no data licence, and the official `wildreceipt.tar` holds images, labels and class lists but no licence file. MMOCR's Apache-2.0 covers its code; the Apache-2.0 on a Hugging Face re-upload is the uploader's | Store name, address, date, total | Same position as SROIE |
| [Find it again!](https://l3i-share.univ-lr.fr/2023Finditagain/index.html) (L3i) | None on the page | Fraud regions; the receipts come from SROIE | Inherits SROIE's missing licence |
| [ExpressExpense](https://expressexpense.com/blog/free-receipt-images-ocr-machine-learning-dataset/) | MIT, stated by the owner | No label files described: 200 images only | Too small for a fit/held-out split, would need hand labeling, possibly generated receipts |
| [CORU](https://huggingface.co/datasets/abdoelsayed/CORU) | Contradictory: card metadata says CC BY 4.0, card text says MIT, the GitHub README states none | Merchant, date, total; no address | Unclear licence, mostly Arabic |
| [XFUND](https://github.com/doc-analysis/XFUND) | CC BY-NC-SA 4.0 | Key-value pairs of forms | Non-commercial, and not receipts |

Even a qualifying public set would only test the calibration code: thresholds calibrated on one document population are "not a portable guarantee across other documents, analyzers, or model versions" ([Microsoft Foundry blog](https://devblogs.microsoft.com/foundry/content-understanding-confidence-grounding-hitl/), whose own lab uses CORD v2). Calibration therefore moves to each client's reviewed documents (D14).

## Demo receipts (fictional)

[`demo/receipt.png`](../demo/receipt.png) and [`demo/receipt-review.png`](../demo/receipt-review.png) are drawn by [`demo/make_receipt.py`](../demo/make_receipt.py) with Pillow's bundled font (Aileron, [`ImageFont.load_default`](https://pillow.readthedocs.io/en/stable/reference/ImageFont.html#PIL.ImageFont.load_default)): the shops, addresses and amounts are invented. Being our own work, the images and the recorded answers about them ([`demo/recordings`](../demo/recordings)) are public, released with the code under this repository's licence. The demo video shows only these receipts and a pile of more fictional ones drawn the same way; it shows no SROIE receipt or value.
