"""The deliberate regression the video shows the eval blocking (shot 5).

One line added to the receipt prompt that looks harmless: keep the address
short. It cuts addresses that run over two lines, so most of them come out
wrong, and accepted without review. Its answers are recorded in the private
recordings repository (``demo/README.md``); the render replays them.

Built in Python rather than kept as a patch: the video no longer shows the
change being applied, and the prompt is changed in memory, so the working
tree is never touched.
"""

from dataclasses import replace

from pydantic import BaseModel

from core.extract import Pack

ANCHOR = "- company and address: the seller's, as printed (usually at the top), not the buyer's.\n"
LINE = "- address: keep it short, only its first line.\n"


def regressed[S: BaseModel](pack: Pack[S]) -> Pack[S]:
    """``pack`` with the regression's line added after its anchor."""
    if pack.instructions.count(ANCHOR) != 1:
        # The prompt changed: the recorded answers to the regressed prompt no
        # longer match it either, so they must be recorded again.
        raise ValueError(
            "the regression's anchor is not once in the prompt; "
            "update demo/regression.py and record its answers again (demo/README.md)"
        )
    return replace(pack, instructions=pack.instructions.replace(ANCHOR, ANCHOR + LINE))
