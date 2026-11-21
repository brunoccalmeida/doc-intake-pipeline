# Shot 4: a deliberate regression in the prompt (demo/regression.patch).
# Caption: Now a one-line prompt change that looks harmless: keep the address short.

Source demo/setup.tape
Show
Type "git apply demo/regression.patch && git diff -U0 -- packs/receipt/__init__.py"
Enter
Wait+Screen /only its first line/
Wait /\$$/
Sleep 6s
