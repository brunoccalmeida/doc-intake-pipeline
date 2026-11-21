# Shared by every shot in demo/shots ("Source demo/setup.tape"): the terminal's
# look and an off-camera start. demo/render.py renders each shot and burns its
# caption in a band below the terminal: Width and Height match the render's
# WIDTH and TERMINAL_HEIGHT.
#
# Every shot starts hidden, on a fresh copy of the repository, so the
# regression patch never touches the mounted repository, even if the render
# stops halfway. The copy leaves out .env (the replay needs no key) and earlier
# reports and renders. Provider and model are the ones the recordings were made
# with, stated so no outside setting changes the keys.
#
# Every Wait names the exact state a shot needs (a prompt, an exit code, a gate
# verdict): a shot that goes wrong stops the render instead of being filmed.
# Waits for slow commands stay hidden, so the video's length is its typing and
# its Sleeps.

Set Shell "bash"
Set FontSize 26
Set Width 1920
Set Height 880
Set Padding 30
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms
Set WindowBar Colorful

Hide
Type "rm -rf /work && mkdir -p /work && tar --exclude=./.venv --exclude=./.env --exclude=./.cache/demo --exclude=./.cache/eval -cf - . | tar -C /work -xf - && cd /work && export PS1='$ ' DOC_INTAKE_PROVIDER=claude DOC_INTAKE_CLAUDE_MODEL=claude-opus-5-5 && clear"
Enter
Wait /\$$/
