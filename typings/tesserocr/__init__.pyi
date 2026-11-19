# Minimal stub: only the API core/ingest.py uses. tesserocr 2.13 ships its
# own __init__.pyi, but it annotates images as "PIL.Image" (the module, not
# the class) without importing PIL, so pyright strict sees the parameter as
# Unknown. Signature copied from that stub; pyright resolves stubPath
# ("typings", pyproject.toml) before the package's own stub.

from PIL import Image

def image_to_text(image: Image.Image, lang: str = ..., path: str = ...) -> str: ...
