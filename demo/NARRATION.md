# Narration script

For a voice-over on the rendered video (`uv run poe demo`, 2:52). About 300 words at a calm pace. Each block starts at the time shown, measured on the render from its scene changes; changing the tape's sleeps moves them.

## Scene 1: the input (0:00)

This is doc-intake-pipeline: it reads documents, including poor scans, and extracts fields with a language model. Here is the input, a faded receipt: a simulated scan, and everything on it is fictional, so it can be shown publicly. The pipeline reads the text with OCR and sends the page image along with it, so the model can check what OCR read against what is printed.

## Scene 2: cited fields (0:25)

Every field comes out with its evidence: the page, and the exact quote it was read from. The pipeline checks each quote against the page before it says ok. Look at the currency: the receipt prints no currency symbol, so the answer is null, with the reason. The model is told never to guess, and the schema enforces it: a value needs a citation, and an empty value needs a reason. A wrong value that looks plausible is the worst output an extraction system can produce; an honest null goes to a person instead.

## Scene 3: measured quality (1:07)

Quality is measured, not claimed. The eval runs the pipeline on twenty public receipts from the SROIE dataset and scores every field against a golden set. This report shows accuracy per field and cost per document. The model's answers are recorded once and replayed, so this runs on every pull request, for free and with the same result every time.

## Scene 4: a regression is blocked (1:53)

Now someone "simplifies" the prompt: keep the address short, only its first line. It looks harmless. The same eval runs, the address score drops, and the gate fails. In CI this is a required check, so the pull request cannot merge until the score is back.

## Close (2:30)

Cited fields, no invented values, and quality measured on every change. The code, the evals and this video's script are all in the repository.
