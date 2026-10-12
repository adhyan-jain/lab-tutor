"""Deterministic backstop for the English-only rule.

The prompts already tell the model to answer in English. This catches the case
where it does not, so a Hindi or Hinglish reply never reaches a student. Pure
code, no model call (code spans, formulas and chemistry names are ignored):

* any Devanagari, or
* two distinct unambiguous Roman-Hindi words, or
* one of them together with two Hindi particles (ka, ki, ke, se, ko, ne).
  The particles never count on their own: "Ka", "Ne" and "se" occur in
  English chemistry text, but not next to "hoti" or "karne".
"""

from __future__ import annotations

import re

_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
_CODE_SPAN = re.compile(r"`[^`]*`|\$\$.*?\$\$|\$[^$\n]*\$", re.DOTALL)
_WORD = re.compile(r"[a-z]+")

# Hindi words that are not English words. Short ambiguous ones are below.
_ROMAN_HINDI = frozenset(
    """hai hain nahi nahin aap kya mein karo karna karne karke kaise kyun kyu samajh samjho samjha
    sakte sakta sakti hota hoti hote wala wali wale waale aur yeh woh iske uske liye abhi theek batao
    dekho pehle phir bhi toh jaata jaati jata jati jaate agar lekin kaun kaha kahan milega milta matlab
    kyunki jaise sabse bahut accha acha chahiye apna apne iska uska unka karte karta karti raha rahe
    rahi gaya gayi hoga hogi kuch sirf zyada yahan wahan hua hui kiya kiye diya liya banao banaya
    mujhe tumhe humein dono""".split()
)
_PARTICLES = frozenset("ka ki ke se ko ne".split())


def looks_non_english(text: str, *, min_hits: int = 2) -> bool:
    if not text:
        return False
    if _DEVANAGARI.search(text):
        return True
    words = _WORD.findall(_CODE_SPAN.sub(" ", text).lower())
    hits = {w for w in words if w in _ROMAN_HINDI}
    if len(hits) >= min_hits:
        return True
    return bool(hits) and sum(w in _PARTICLES for w in words) >= 2


class EnglishStreamGate:
    """The same check, applied to a reply while it streams.

    Text is held back until there is enough of it to judge (a short opening
    can look like anything), then passed through. Once the text so far looks
    non-English nothing more is forwarded, and `feed` reports whether the
    browser must discard what it already showed. The saved reply that ends the
    stream is always the authority; this only stops a Hindi/Hinglish draft
    from being displayed while it is being replaced.
    """

    def __init__(self, hold_chars: int = 48) -> None:
        self._hold = hold_chars
        self._text = ""
        self._sent = 0
        self.blocked = False

    def feed(self, chunk: str) -> tuple[str, bool]:
        """Returns (text to forward now, whether to reset the shown draft)."""
        if self.blocked:
            return "", False
        self._text += chunk
        if looks_non_english(self._text):
            self.blocked = True
            return "", self._sent > 0
        if len(self._text) < self._hold:
            return "", False
        out, self._sent = self._text[self._sent:], len(self._text)
        return out, False

    def flush(self) -> str:
        """Whatever is still held when the stream ends (a short reply)."""
        if self.blocked:
            return ""
        out, self._sent = self._text[self._sent:], len(self._text)
        return out
