# Shot 2: every field with its evidence (a recorded answer from Claude, replayed).
# Caption: Out: each value found, with the exact quote it was read from on the page.

Source demo/setup.tape
Show
Type "uv run poe extract --replay demo/recordings demo/receipt.png 2>/dev/null | uv run python -m demo.show_result"
Hide
Enter
Wait+Screen@60s /status: ok/
Wait /\$$/
Show
Sleep 7s
