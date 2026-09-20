"""Model output must render cleanly in the chat.

Basis-set names carry asterisks (6-31G*, 6-31G**) that collide with markdown
bold markers; a model that bolds them produces text like `**6-31G***` that a
markdown renderer shows as raw asterisks. These pin the deterministic repair,
using the exact strings seen in live answers.
"""

from __future__ import annotations

import pytest

from backend.llm import telemetry
from backend.retrieval.pipeline import _normalise_markdown, answer_question

CASES = [
    # seen live
    ("**B3LYP** method with the **6-31G*** basis set.", "**B3LYP** method with the `6-31G*` basis set."),
    (r"**B3LYP** method with the **6-31G**\*\* basis set.", "**B3LYP** method with the `6-31G**` basis set."),
    ("look for *** OPTIMIZATION RUN DONE ***.", "look for `*** OPTIMIZATION RUN DONE ***`."),
    # bold wrapping the name
    ("**6-31G**", "`6-31G`"),
    ("**Basis: 6-31G**", "**Basis: `6-31G`**"),
    ("**Basis: 6-31G***", "**Basis: `6-31G*`**"),
    ("**Pick 6-31G**: ok", "**Pick `6-31G`**: ok"),
    ("**6-31G** and **6-31G***", "`6-31G` and `6-31G*`"),
    ("**6-31G* is good**", "**`6-31G*` is good**"),
    # plain text
    ("use 6-31G* and 6-31G**.", "use `6-31G*` and `6-31G**`."),
    ("6-311++G** works", "`6-311++G**` works"),
    # left alone
    ("already `6-31G*` fine and 6-31G**", "already `6-31G*` fine and `6-31G**`"),
    ("keep `*** OPTIMIZATION RUN DONE ***` as is", "keep `*** OPTIMIZATION RUN DONE ***` as is"),
    ("no basis here, **bold** text and 1-2 steps", "no basis here, **bold** text and 1-2 steps"),
]


@pytest.mark.parametrize("raw,expected", CASES)
def test_basis_sets_and_banner_become_inline_code(raw, expected):
    assert _normalise_markdown(raw) == expected


@pytest.mark.parametrize("raw,_expected", CASES)
def test_normalising_twice_changes_nothing(raw, _expected):
    once = _normalise_markdown(raw)
    assert _normalise_markdown(once) == once


def test_multiline_answers_are_handled_line_by_line():
    raw = "1. Pick **6-31G***.\n2. Then **B3P** with the **6-31G**\\*\\*.\n3. Done."
    assert _normalise_markdown(raw) == "1. Pick `6-31G*`.\n2. Then **B3P** with the `6-31G**`.\n3. Done."


@pytest.mark.asyncio
async def test_the_pipeline_returns_normalised_text(monkeypatch):
    from backend.llm.client import LLMReply

    class _Bolding:
        name = "fake"
        supports_context_cache = False

        async def complete(self, *, system, user, max_tokens=None, temperature=None):
            telemetry.record_call()
            return LLMReply(
                text="Choose the **6-31G*** basis set and look for *** OPTIMIZATION RUN DONE ***.",
                backend="fake",
                model="m",
            )

    monkeypatch.setattr("backend.retrieval.pipeline.get_backend", lambda: _Bolding())
    result = await answer_question("which basis set do I choose", active_experiment="exp07")
    assert "`6-31G*`" in result.text
    assert "`*** OPTIMIZATION RUN DONE ***`" in result.text
    assert "**6-31G" not in result.text
