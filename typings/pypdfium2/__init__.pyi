# Minimal stub: only the API core/ingest.py uses. pypdfium2 5.15 ships no
# type information (no py.typed), so pyright strict reports every call as
# Unknown. Signatures copied from the installed source's docstrings; the
# ingest tests exercise each one, so a drifted stub fails a test, not runtime.
# Pyright resolves stubPath ("typings", pyproject.toml) before the package.

from os import PathLike
from types import TracebackType
from typing import Self

from PIL import Image

class PdfiumError(RuntimeError): ...

class PdfBitmap:
    def to_pil(self) -> Image.Image: ...

class PdfTextPage:
    def get_text_bounded(
        self,
        left: float | None = None,
        bottom: float | None = None,
        right: float | None = None,
        top: float | None = None,
        errors: str = "ignore",
    ) -> str: ...

class PdfPage:
    def get_textpage(self) -> PdfTextPage: ...
    def render(self, scale: float = 1, rotation: int = 0) -> PdfBitmap: ...

class PdfDocument:
    def __init__(
        self,
        input: str | PathLike[str] | bytes,
        password: str | None = None,
        autoclose: bool = False,
    ) -> None: ...
    def __enter__(self) -> Self: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...
    def __len__(self) -> int: ...
    def __getitem__(self, i: int) -> PdfPage: ...
