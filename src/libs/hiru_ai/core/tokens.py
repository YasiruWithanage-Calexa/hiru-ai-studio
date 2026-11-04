"""A cheap, offline estimate of tokens. No tokenizer download: tests never touch the network."""
from __future__ import annotations

import math


def tokens_of(text: str) -> int:
    """About 4 characters a token in Latin text, about 1.5 in Sinhala; it errs high, the safe side of a budget."""
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    return math.ceil(ascii_chars / 4 + (len(text) - ascii_chars) / 1.5)
