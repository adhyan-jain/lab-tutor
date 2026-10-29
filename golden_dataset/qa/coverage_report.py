"""Coverage report: per-experiment question counts, status mix, and which
routing vocabulary has zero question coverage.

The brief asks (section 10) for "Experiment 7 page/section -> number of
golden questions -> pass rate", with the explicit requirement that no
important screenshot/page go uncovered. There are no pages yet -- the
IACHY102 manual is not in this repository (`docs/final_audit.md`
§0) -- so a page-level report would be fabricated structure over nothing.

What this script reports instead, honestly, at the level actually
available today:

* **Question count and live status mix per experiment**, from
  `golden_dataset/qa/expNN.json` (each case's `expected_behavior` was
  computed by the live pipeline at generation time, not authored).
* **Vocabulary coverage**: which of an experiment's routing terms
  (`backend/scope/ontology.py`) appear in zero generated questions. A
  term with zero coverage is a term the golden dataset does not actually
  exercise -- the direct analogue of an uncovered page, at the
  granularity this phase has real data for.

Once the manual is ingested and pages/sections exist as real metadata on
`Chunk` objects, this script is the place to add the page-level table
the brief describes -- swap the vocabulary-coverage section for a
page/section groupby over `Chunk.page`/`Chunk.section` for chunks that
were actually cited by an `IN_SCOPE_SUPPORTED` case, and flag any page
tagged as visual (`Chunk.visual_available`) that no case cites.

Usage:  python golden_dataset/qa/coverage_report.py
"""

from __future__ import annotations

import json
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent.parent))

from backend.scope import ontology  # noqa: E402


def _load_cases(experiment_id: str) -> list[dict]:
    path = ROOT / f"{experiment_id}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def _term_hit(term: str, question: str) -> bool:
    lowered = question.lower()
    if " " in term:
        return term in lowered
    import re

    return re.search(rf"\b{re.escape(term)}\b", lowered) is not None


def report() -> dict:
    all_report: dict[str, dict] = {}
    for topic in ontology.all_topics():
        cases = _load_cases(topic.id)
        status_counts = Counter(c["expected_behavior"] for c in cases)
        scope_counts = Counter(c["scope_label_intent"] for c in cases)

        vocabulary = sorted(topic.strong_terms | topic.software) if topic.routable else []
        questions_text = " \n".join(c["user_question"] for c in cases)
        uncovered = [t for t in vocabulary if not _term_hit(t, questions_text)]

        answerable = sum(
            1 for c in cases if c["expected_behavior"] in ("in_scope_supported", "adjacent_supported")
        )

        all_report[topic.id] = {
            "title": topic.title,
            "priority": topic.priority,
            "routable": topic.routable,
            "case_count": len(cases),
            "status_mix": dict(status_counts),
            "scope_mix": dict(scope_counts),
            "answerable_today": answerable,
            "answerable_rate_today": round(answerable / len(cases), 3) if cases else None,
            "vocabulary_terms": len(vocabulary),
            "vocabulary_uncovered": uncovered,
        }
    return all_report


def print_report(data: dict) -> None:
    print(f"{'experiment':10} {'priority':4} {'cases':>6} {'answerable_today':>17} {'uncovered_terms':>16}")
    for experiment_id, row in sorted(data.items()):
        print(
            f"{experiment_id:10} {row['priority']:4} {row['case_count']:6d} "
            f"{row['answerable_today']:17d} {len(row['vocabulary_uncovered']):16d}"
        )
    print()
    for experiment_id, row in sorted(data.items()):
        if row["vocabulary_uncovered"]:
            print(f"{experiment_id}: uncovered routing terms -> {row['vocabulary_uncovered']}")


def main() -> int:
    data = report()
    print_report(data)
    (ROOT / "coverage_report.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {ROOT / 'coverage_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
