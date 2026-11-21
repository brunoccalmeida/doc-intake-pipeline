# The demo video, recorded as code with VHS (https://github.com/charmbracelet/vhs).
# Render it with "uv run poe demo" (demo/README.md): replay only, no key, no cost.
# Captions are shell comments typed like commands: VHS's README documents no
# caption or overlay command (v0.12.1).
#
# Every Wait names the exact state a scene needs (a prompt, an exit code, a
# gate verdict): a scene that goes wrong stops the render instead of filming it.
# Sleeps leave time for the narration (NARRATION.md) over each scene.

Output .cache/demo/doc-intake-demo.mp4

Set Shell "bash"
Set FontSize 18
Set Width 1600
Set Height 960
Set Padding 30
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms
Set WindowBar Colorful

# Off camera: work on a copy, so the regression patch never touches the
# mounted repository, even if the render stops halfway. The copy leaves out
# .env (the replay needs no key) and earlier reports, which a failed eval
# would otherwise leave on screen. Provider and model are the defaults the
# recordings were made with, stated so no outside setting changes the keys.
Hide
Type "mkdir -p .cache/demo /work && tar --exclude=./.venv --exclude=./.env --exclude=./.cache/demo --exclude=./.cache/eval -cf - . | tar -C /work -xf - && cd /work && export PS1='$ ' DOC_INTAKE_PROVIDER=claude DOC_INTAKE_CLAUDE_MODEL=claude-opus-5-5 && clear"
Enter
Wait /\$$/
Show

# Scene 1: the input.
Type "# A faded receipt, a simulated scan: everything printed on it is fictional."
Enter
Sleep 1s
Type "chafa --size 60x30 demo/receipt.png"
Enter
Wait /\$$/
Sleep 20s

# Scene 2: cited fields, and a null with its reason instead of a guess.
Type "clear"
Enter
Type "# Fields come out with the quote each was read from (a recorded answer from Claude, replayed)."
Enter
Type "uv run poe extract --replay demo/recordings demo/receipt.png 2>/dev/null | uv run python -m demo.show_result"
Enter
Wait+Screen@60s /status: ok/
Wait /\$$/
Sleep 1s
Type "# No currency is printed, so it comes out null with the reason: never a guess."
Enter
Sleep 28s

# Scene 3: measured quality.
Type "clear"
Enter
Type "# Quality is measured on 20 public receipts (SROIE) against a golden set, on every PR."
Enter
Type "# The exit code is what CI reads; the report is what a reviewer reads."
Enter
Type `uv run poe eval 2>/dev/null; echo "exit code: $?"`
Enter
Wait+Screen@180s /exit code: 0/
Sleep 1s
Type "clear && cat .cache/eval/report.md"
Enter
Wait+Screen /Gate: passed/
Wait /\$$/
Sleep 22s

# Scene 4: a worse prompt is blocked.
Type "clear"
Enter
Type "# Now a deliberate regression: the prompt asks for only the first line of the address."
Enter
Type "git apply demo/regression.patch && git diff -U0 -- packs/receipt/__init__.py"
Enter
Wait+Screen /only its first line/
Wait /\$$/
Sleep 6s
Type "# Same eval, same command CI runs as a required check:"
Enter
Type `rm .cache/eval/report.md && uv run poe eval 2>/dev/null; echo "exit code: $?"`
Enter
Wait+Screen@180s /exit code: 1/
Sleep 1s
Type "clear && sed '/^## Documents by status/q' .cache/eval/report.md"
Enter
Wait+Screen /Gate: failed/
Wait /\$$/
Sleep 1s
Type "# The pull request cannot merge until the score is back."
Enter
Sleep 22s
