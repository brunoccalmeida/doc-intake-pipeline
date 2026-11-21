# Shot 5: the eval blocks the regression of shot 4. The eval's run (about 20 s)
# is cut; its exit code and the gate's verdict are shown.
# Caption: CI runs this eval on every pull request, and it fails: wrong addresses would reach clients unchecked.

Source demo/setup.tape
Type "git apply demo/regression.patch"
Enter
Wait /\$$/
Type "clear"
Enter
Wait /\$$/
Show
Type `uv run poe eval 2>/dev/null; echo "exit code: $?"`
Hide
Enter
Wait+Screen@180s /exit code: 1/
Wait /\$$/
Show
Sleep 1s
Type "sed '/^## Accuracy/,$d' .cache/eval/report.md"
Enter
Wait+Screen /wrong values accepted without review/
Wait /\$$/
Sleep 9s
