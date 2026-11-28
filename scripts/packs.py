"""The ``--pack`` option every script that reads documents or their review takes.

The receipt pack is the default, so every documented command keeps its
meaning. Each script dispatches with one call per pack, not a lookup: ``Pack``
is invariant, so each call keeps its own schema type (docs/ARCHITECTURE.md D24).
"""

import argparse

from doc_intake.packs.invoice import INVOICE
from doc_intake.packs.receipt import RECEIPT

DEFAULT_PACK = RECEIPT.name
PACK_NAMES = (RECEIPT.name, INVOICE.name)


def add_pack_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--pack",
        choices=PACK_NAMES,
        default=DEFAULT_PACK,
        help=f"the document type (default {DEFAULT_PACK})",
    )
