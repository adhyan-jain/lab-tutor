"""Scope classification and status resolution.

## The ordering constraint that makes this work

`classify_scope()` runs **before** retrieval and never sees its result.
`resolve_status()` runs after, and may only choose *within* the level
that classification already fixed.

That ordering is the whole design. If scope could be revised by
retrieval, then "we found nothing" and "this is not our subject" would
converge on the same answer, which is exactly the failure the brief
calls out: a student asking a normal Experiment 7 question would be told
their experiment is off-topic. Keeping the decision upstream of the
lookup makes that structurally impossible rather than merely discouraged,
and `test_scope_classifier.py` asserts it by feeding empty evidence to
every in-scope case in the golden set.

## How the level is chosen

Signals, in order of strength:

1. An explicit experiment number ("exp 7") — decisive for routing.
2. Strong ontology terms (HOMO, staggered, ethyl acetate, RGB).
3. Software names, weighted across the experiments that share them.
4. Weak ontology terms.
5. General domain vocabulary — in-domain, but not enough to route.
6. Out-of-domain vocabulary — only decisive when nothing above fires.

Level 1 versus Level 2 is then decided by what is being *asked for*:
procedural markers ("how do I", "which button", "what do I fill in")
indicate the documented procedure; adjacent markers ("why does ...
physically", "is there a better method") indicate background the manual
does not carry.

## Precision bias on Level 3

Refusing a real question is much worse than accepting a marginal one. A
refused student stops asking; a marginal question just costs a retrieval
that finds nothing and degrades to a polite "I could not find this".
So out-of-scope requires out-of-domain evidence *and* the absence of
in-domain evidence, and the safety/off-topic triage in
`socratic_engine/triage.py` is consulted first for the cases where a
fast, deterministic refusal genuinely is correct.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.scope import ontology
from backend.scope.normalize import NormalizedQuery, normalize
from backend.scope.statuses import AnswerStatus, ScopeLevel
from backend.socratic_engine import triage

#: Scores. Relative magnitudes matter, absolute values do not.
_CODE_REQUEST_RE = re.compile(
    r"\b(?:give|write|send|show|type|need|want|provide|paste)\b[^.?!]{0,40}\b(?:code|program|script|function|implementation|snippet)\b"
    r"|\b(?:code|program|script|implementation)\s+(?:for|of|to)\b",
    re.IGNORECASE,
)
_PROGRAMMING_RE = re.compile(
    r"\blinked\s+list\b|\bbinary\s+(?:tree|search)\b|\bdata\s+structures?\b|\bc\+\+|\bc\s+(?:language|program\w*|code)\b"
    r"|\bin\s+c\b|\bjava(?:script)?\b|\bpython\b|\balgorithm\b|\breversal\b|\bsorting\b|\bleetcode\b",
    re.IGNORECASE,
)

_W_EXPLICIT = 100.0
_W_STRONG = 10.0
_W_SOFTWARE = 4.0
_W_WEAK = 2.0

#: A routed experiment must beat the runner-up by this ratio, or the
#: question is treated as in-domain but unrouted. Answering the wrong
#: experiment's procedure confidently is worse than admitting ambiguity.
_AMBIGUITY_RATIO = 1.5

#: Weak terms are never decisive on their own. "burette", "titration",
#: "concentration" and "energy" are shared wet-lab and computational
#: vocabulary; an experiment is claimed only on a strong term, a software
#: name, or the student naming the number. Weak terms then break ties and
#: raise confidence. Without this rule "what is a burette" routes to
#: experiment 2 and gets answered with that experiment's procedure.
_MIN_ROUTING_SCORE = 2.0


@dataclass(frozen=True)
class ScopeDecision:
    """The retrieval-independent verdict on one question."""

    level: ScopeLevel
    query: NormalizedQuery
    experiment_id: str | None = None
    #: 0.0-1.0. Drives whether ambiguity is surfaced, not whether an
    #: answer is attempted.
    confidence: float = 0.0
    matched_terms: tuple[str, ...] = ()
    #: Per-experiment routing scores, for debugging a misroute.
    scores: dict[str, float] = field(default_factory=dict)
    rationale: str = ""
    #: Set when triage short-circuited (safety, distress). The caller must
    #: honour this before doing anything else.
    triage_intent: triage.Intent | None = None
    #: True when the question is recognisably about our subject but could
    #: not be attached to a specific experiment.
    in_domain_unrouted: bool = False

    @property
    def experiment_label(self) -> str:
        if self.experiment_id is None:
            return "this experiment"
        try:
            topic = ontology.get_topic(self.experiment_id)
        except KeyError:
            # A plugin registered without a matching ontology entry (e.g. a
            # test fixture, or a future plugin mid-rollout) must not crash
            # a live Q&A request just to produce a label string.
            return self.experiment_id
        return topic.title if topic.routable else f"experiment {int(self.experiment_id[3:])}"

    @property
    def is_in_scope(self) -> bool:
        return self.level is not ScopeLevel.OUT_OF_SCOPE


def classify_scope(
    message: str,
    *,
    active_experiment: str | None = None,
    normalized: NormalizedQuery | None = None,
) -> ScopeDecision:
    """Classify one message. Deterministic, model-free, retrieval-free."""
    query = normalized if normalized is not None else normalize(message)

    # Safety and distress outrank every other consideration, and are
    # already handled deterministically. Do not re-implement them here.
    intent = triage.classify(message)
    if intent in (
        triage.Intent.SAFETY_INCIDENT,
        triage.Intent.SAFETY_QUESTION,
        triage.Intent.DISTRESS,
    ):
        return ScopeDecision(
            level=ScopeLevel.DIRECT,
            query=query,
            experiment_id=active_experiment,
            confidence=1.0,
            rationale=f"triage short-circuit: {intent.value}",
            triage_intent=intent,
        )

    text = query.text
    tokens = set(query.tokens)

    scores, matched, decisive = _route(query, tokens, text)

    in_domain = _in_domain_evidence(tokens, text)
    out_domain = _out_of_domain_evidence(tokens, text)
    # A hit on only the generic, high-frequency subset ("lab", "software",
    # "file"...) must not by itself block a refusal: those words appear in
    # ordinary off-topic phrases too ("software engineering interview",
    # "lab report"). Real domain evidence -- a chemistry term, a software
    # *name*, an experiment number -- still blocks it.
    substantive_in_domain = in_domain - ontology._WEAK_GENERIC_DOMAIN_TERMS

    # Both out-of-scope checks below are decided from the MESSAGE alone --
    # `decisive`, `substantive_in_domain` and `query.explicit_experiments`,
    # never from `active_experiment`. A session left open on experiment 7
    # must not immunise "what is the best gpu for gaming" from refusal
    # just because the last message happened to be about experiment 7;
    # the demo script (scripts/demo_exp7.py) is what surfaced this as a
    # real bug rather than a hypothetical one -- session carryover was
    # letting exactly this kind of message slip through uncaught.
    has_message_evidence = bool(decisive) or bool(query.explicit_experiments)

    # An explicit request to write code in a programming language is never a
    # lab question, even when it also names a lab program ("learn ORCA, but
    # first give me the C code") or is wrapped in urgency. Needs both a code
    # request and a programming-language/data-structure term, so "how do I
    # write the ORCA input file" is unaffected.
    if _CODE_REQUEST_RE.search(text) and _PROGRAMMING_RE.search(text):
        return ScopeDecision(
            level=ScopeLevel.OUT_OF_SCOPE,
            query=query,
            confidence=0.95,
            scores=scores,
            rationale="explicit request for programming code",
            triage_intent=intent,
        )

    # Level 3 requires positive out-of-domain evidence AND the absence of
    # substantive in-domain evidence. Both halves matter: "why is chair
    # more stable" contains no out-of-domain terms, and "is a gaming gpu
    # faster at running orca" contains both and must not be refused.
    if out_domain and not substantive_in_domain and not has_message_evidence:
        return ScopeDecision(
            level=ScopeLevel.OUT_OF_SCOPE,
            query=query,
            confidence=0.9,
            matched_terms=tuple(sorted(out_domain)),
            scores=scores,
            rationale=(
                f"out-of-domain terms {sorted(out_domain)} with no competing "
                "in-domain evidence"
            ),
            triage_intent=intent,
        )

    if intent is triage.Intent.OFF_SCOPE and not has_message_evidence and not substantive_in_domain:
        return ScopeDecision(
            level=ScopeLevel.OUT_OF_SCOPE,
            query=query,
            confidence=0.8,
            scores=scores,
            rationale="triage off-scope pattern with no in-domain evidence",
            triage_intent=intent,
        )

    experiment_id, confidence, ambiguous = _pick(
        scores, decisive, query, active_experiment
    )

    # Anaphora ("what comes after this screen") inherits the session's
    # experiment: the referent is the conversation, not the message.
    if experiment_id is None and query.has_anaphora and active_experiment:
        experiment_id = active_experiment
        confidence = max(confidence, 0.5)

    level = (
        ScopeLevel.ADJACENT
        if _is_adjacent(text, tokens, experiment_id, in_domain)
        else ScopeLevel.DIRECT
    )

    return ScopeDecision(
        level=level,
        query=query,
        experiment_id=experiment_id,
        confidence=confidence,
        matched_terms=tuple(sorted(matched)),
        scores=scores,
        rationale=_rationale(experiment_id, ambiguous, in_domain, level),
        triage_intent=intent,
        in_domain_unrouted=experiment_id is None and bool(in_domain or matched),
    )


def _route(
    query: NormalizedQuery, tokens: set[str], text: str
) -> tuple[dict[str, float], set[str], set[str]]:
    """Score each experiment, and record which ones have *decisive* evidence.

    Returns ``(scores, matched_terms, decisive_ids)``. An experiment is
    decisive only if a strong term, a software name, or an explicit
    experiment number pointed at it.
    """
    scores: dict[str, float] = {}
    matched: set[str] = set()
    decisive: set[str] = set()

    for topic in ontology.routable_topics():
        score = 0.0
        if topic.id in query.explicit_experiments:
            score += _W_EXPLICIT
            matched.add(topic.id)
            decisive.add(topic.id)
        for term in topic.strong_terms:
            if _contains(term, tokens, text):
                score += _W_STRONG
                matched.add(term)
                decisive.add(topic.id)
        for term in topic.software:
            if _contains(term, tokens, text):
                score += _W_SOFTWARE
                matched.add(term)
                decisive.add(topic.id)
        for term in topic.weak_terms:
            if _contains(term, tokens, text):
                score += _W_WEAK
                matched.add(term)
        if score:
            scores[topic.id] = score

    # An explicitly named experiment that has no ontology yet still routes:
    # the student told us which one, and not knowing its subject matter is
    # our gap, not a reason to ignore them.
    for named in query.explicit_experiments:
        scores.setdefault(named, _W_EXPLICIT)
        matched.add(named)
        decisive.add(named)

    return scores, matched, decisive


def _pick(
    scores: dict[str, float],
    decisive: set[str],
    query: NormalizedQuery,
    active_experiment: str | None,
) -> tuple[str | None, float, bool]:
    if not scores:
        # No term evidence at all: fall back to session context if any.
        return (active_experiment, 0.35 if active_experiment else 0.0, False)

    if query.explicit_experiments:
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        return (ranked[0][0], 1.0, False)

    # Weak-only evidence does not claim an experiment. The question is
    # still in-domain; it just is not attributable to one of them.
    candidates = {k: v for k, v in scores.items() if k in decisive}
    if not candidates:
        return (active_experiment, 0.3 if active_experiment else 0.0, False)

    ranked = sorted(candidates.items(), key=lambda kv: (-kv[1], kv[0]))
    top_id, top_score = ranked[0]

    if top_score < _MIN_ROUTING_SCORE:
        return (active_experiment, 0.3 if active_experiment else 0.0, False)

    runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
    ambiguous = runner_up > 0 and top_score < runner_up * _AMBIGUITY_RATIO

    if ambiguous:
        # The two computational experiments share Avogadro, ORCA,
        # "optimisation" and "energy". When the evidence genuinely does not
        # separate them, prefer the session's own experiment over a
        # coin-flip between them.
        if active_experiment and active_experiment in candidates:
            return (active_experiment, 0.55, True)
        return (top_id, 0.4, True)

    confidence = min(0.95, 0.5 + 0.45 * (1.0 - (runner_up / top_score if top_score else 0)))
    return (top_id, confidence, False)


def _contains(term: str, tokens: set[str], text: str) -> bool:
    if " " in term or "/" in term or "(" in term:
        return term in text
    return term in tokens


def _in_domain_evidence(tokens: set[str], text: str) -> set[str]:
    hits = tokens & ontology.GENERAL_DOMAIN_TERMS
    hits |= tokens & ontology.SOFTWARE_TERMS
    for topic in ontology.routable_topics():
        hits |= tokens & topic.strong_terms
        hits |= tokens & topic.software
    for term in ("beer lambert", "rate constant", "ethyl acetate", "molecular orbital"):
        if term in text:
            hits.add(term)
    return hits


def _out_of_domain_evidence(tokens: set[str], text: str) -> set[str]:
    hits = tokens & ontology.OUT_OF_DOMAIN_TERMS
    for term in ontology.OUT_OF_DOMAIN_TERMS:
        if " " in term and term in text:
            hits.add(term)
    return hits


def _is_adjacent(
    text: str, tokens: set[str], experiment_id: str | None, in_domain: set[str]
) -> bool:
    """Whether the question asks for background rather than the procedure.

    Ties go to DIRECT. A question that is really adjacent but treated as
    direct retrieves manual chunks, finds nothing conclusive, and lands on
    `IN_SCOPE_RETRIEVAL_INSUFFICIENT` — which is honest. The reverse error
    labels a procedure question "supplementary" and answers it from a
    general explainer, which is the failure mode that actually misleads a
    student about what they are assessed on.
    """
    adjacent_hits = sum(1 for m in ontology.ADJACENT_MARKERS if m in text)
    procedural_hits = sum(1 for m in ontology.PROCEDURAL_MARKERS if m in text)
    if adjacent_hits == 0:
        return False
    return adjacent_hits > procedural_hits


def _rationale(
    experiment_id: str | None, ambiguous: bool, in_domain: set[str], level: ScopeLevel
) -> str:
    if experiment_id and ambiguous:
        return f"routed to {experiment_id} under ambiguity; runner-up was close"
    if experiment_id:
        return f"routed to {experiment_id} ({level.value})"
    if in_domain:
        return (
            "recognised as in-domain but not attributable to one experiment "
            f"({sorted(in_domain)[:4]})"
        )
    return "no routing evidence found"


# ---------------------------------------------------------------------------
# Status resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceSummary:
    """What retrieval produced, reduced to what status resolution needs."""

    #: Passages from tier A or B that survived relevance filtering.
    official_count: int = 0
    #: Passages from curated tier C material.
    supplementary_count: int = 0
    #: Best relevance score among official passages.
    top_official_score: float = 0.0
    #: Best relevance score among supplementary passages.
    top_supplementary_score: float = 0.0
    #: Set when ingestion or retrieval reported an A-vs-B contradiction.
    conflict: bool = False
    #: Set when the corpus itself is missing, as opposed to searched and
    #: found wanting. Distinguished so an empty index does not masquerade
    #: as thorough coverage.
    corpus_unavailable: bool = False

    @property
    def has_official(self) -> bool:
        return self.official_count > 0

    @property
    def has_supplementary(self) -> bool:
        return self.supplementary_count > 0


#: Minimum relevance for a passage to count as support. A passage that
#: merely mentions the experiment number is not evidence for a claim.
MIN_SUPPORT_SCORE = 0.15


def resolve_status(
    decision: ScopeDecision, evidence: EvidenceSummary
) -> AnswerStatus:
    """Combine scope with evidence. May not revise the level.

    The invariant, asserted in the tests: no value of `evidence` turns an
    in-scope decision into `OUT_OF_SCOPE`.
    """
    if decision.level is ScopeLevel.OUT_OF_SCOPE:
        return AnswerStatus.OUT_OF_SCOPE

    if evidence.conflict:
        return AnswerStatus.NEEDS_HUMAN_REVIEW

    if decision.level is ScopeLevel.DIRECT:
        if evidence.has_official and evidence.top_official_score >= MIN_SUPPORT_SCORE:
            return AnswerStatus.IN_SCOPE_SUPPORTED
        return AnswerStatus.IN_SCOPE_RETRIEVAL_INSUFFICIENT

    # Adjacent. Official material still wins if it happens to cover it --
    # the manual answering an adjacent question is a better outcome than
    # a supplementary source doing so.
    if evidence.has_official and evidence.top_official_score >= MIN_SUPPORT_SCORE:
        return AnswerStatus.IN_SCOPE_SUPPORTED
    if (
        evidence.has_supplementary
        and evidence.top_supplementary_score >= MIN_SUPPORT_SCORE
    ):
        return AnswerStatus.ADJACENT_SUPPORTED
    return AnswerStatus.ADJACENT_UNSUPPORTED


def classify_and_resolve(
    message: str,
    evidence: EvidenceSummary,
    *,
    active_experiment: str | None = None,
) -> tuple[ScopeDecision, AnswerStatus]:
    decision = classify_scope(message, active_experiment=active_experiment)
    return decision, resolve_status(decision, evidence)
