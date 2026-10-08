"""Deterministic backstop for the English-only rule.

The prompts already tell the model to answer in English. This catches the case
where it does not, so a Hindi or Hinglish reply never reaches a student. Pure
code, no model call: Devanagari script, or two or more distinct Roman-Hindi
function words in prose (code spans, formulas and chemistry names are ignored).
"""

from __future__ import annotations

import re

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_CODE_SPAN = re.compile(r"`[^`]*`|\$\$.*?\$\$|\$[^$\n]*\$", re.DOTALL)
_WORD = re.compile(r"[a-z]+")

# Function words that are not English words. Content words and ambiguous
# short ones (ka, ki, ke, se, ho) are left out on purpose.
_ROMAN_HINDI = frozenset(
    """hai hain nahi nahin aap kya mein karo karna karke kaise kyun kyu samajh samjho samjha sakte sakta
    sakti hota hoti hote wala wali aur yeh woh iske uske liye abhi theek batao dekho pehle phir bhi toh
    jaata jaati agar lekin kaun kaha kahan milega milta""".split()
)


def looks_non_english(text: str, *, min_hits: int = 2) -> bool:
    if not text:
        return False
    if _DEVANAGARI.search(text):
        return True
    prose = _CODE_SPAN.sub(" ", text).lower()
    hits = {w for w in _WORD.findall(prose) if w in _ROMAN_HINDI}
    return len(hits) >= min_hits
