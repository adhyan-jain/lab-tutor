"""Runnable Experiment 7 demo conversation.

Drives `backend.retrieval.pipeline.answer_question` through the
conversation scripted in `docs/exp07.md`, printing each turn's
status, routed experiment, answer text and citations exactly as the
pipeline produces them today -- no service, database, or LLM API key
required (`use_llm=False` forces the deterministic extractive path,
which is also what happens automatically whenever no LLM backend is
configured; see `backend/retrieval/pipeline.py::_generate_answer`).

This demonstrates the plumbing honestly: with the IACHY102 manual not
yet in the repository (`docs/final_audit.md` §0), the direct
procedural questions correctly resolve to
`IN_SCOPE_RETRIEVAL_INSUFFICIENT` rather than a guessed answer. The
adjacent-theory question resolves to `ADJACENT_SUPPORTED` from the real
`knowledge/adjacent/` corpus, and the out-of-scope turn is refused
before any retrieval runs. Once the manual is ingested, re-running this
script is the fastest way to see which of these flip to
`IN_SCOPE_SUPPORTED`.

Usage:  python scripts/demo_exp7.py
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.retrieval.index import get_index, reset_index_cache  # noqa: E402
from backend.retrieval.pipeline import answer_question  # noqa: E402

TURNS = [
    "hey how to do exp 7",
    "gabedit me ch4 kaise banau",
    "which method and basis set should i use",
    "orca input generator kaha hai",
    "job completion message nahi aa raha, normal hai kya",
    "after optimization what next",
    "orca ka output kaha milega",
    "avogadro me homo kaise dekhe",
    "where is HOMO LUMO in the output",
    "how calculate orbital contribution",
    "what do i fill in the table",
    "oxygen molecule same process?",
    "which screen comes after this one",
    "why does DFT work physically",
    "what is the best gpu for gaming",
]


def _rule(char: str = "-", width: int = 78) -> str:
    return char * width


async def main() -> None:
    reset_index_cache()
    index = get_index()
    print(f"Index built: {len(index)} chunk(s) from currently-ingestible sources.")
    print(_rule("="))

    active_experiment = None
    for turn_number, message in enumerate(TURNS, start=1):
        result = await answer_question(
            message, active_experiment=active_experiment, index=index, use_llm=False
        )
        if result.decision.experiment_id:
            active_experiment = result.decision.experiment_id

        print(f"[{turn_number:02d}] Student: {message}")
        print(f"     scope={result.decision.level.value}  experiment={result.decision.experiment_id}  status={result.status.value}")
        print(f"     Tutor: {result.text}")
        if result.citations:
            for citation in result.citations:
                print(f"       - {citation.text}")
        print(_rule())

    print("Demo complete. See docs/exp07.md for what each turn is meant to show.")


if __name__ == "__main__":
    asyncio.run(main())
