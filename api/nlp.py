"""Shared spaCy pipeline.

`spacy.load()` is expensive (it reads the model into memory), so it must never
run per-request. `get_nlp()` loads the model on first use and caches it, so
every caller reuses the same pipeline. Loading lazily (rather than at import
time) keeps unrelated commands like migrations from paying the startup cost.
"""
import functools

import spacy


@functools.lru_cache(maxsize=1)
def get_nlp():
    """Return the shared spaCy English pipeline, loading it once on first call."""
    return spacy.load("en_core_web_sm")
