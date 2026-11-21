# Shot 3: the same screen as shot 2 (the same command, off camera), with the
# point it makes about the currency.
# Caption: No currency is printed, so it comes out null with the reason. Never a plausible guess.

Source demo/setup.tape
Type "uv run poe extract --replay demo/recordings demo/receipt.png 2>/dev/null | uv run python -m demo.show_result"
Enter
Wait+Screen@60s /currency +null/
Wait /\$$/
Show
Sleep 7s
