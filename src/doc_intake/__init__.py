"""Document intake core: read a document, extract fields with an LLM, return them validated.

``core`` is the vendor-neutral engine, ``packs`` holds one schema per document
type and ``providers`` the LLM implementations (``docs/ARCHITECTURE.md`` D18).
"""
