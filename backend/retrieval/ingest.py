"""Turning a manifest-declared document into provenance-carrying chunks.

Reproducibility (brief §7) comes from three things working together:

* Chunk IDs are deterministic (`make_chunk_id`), keyed on
  `(document_id, version, locator)`. Re-ingesting the same PDF at the
  same version produces the same IDs; a revised manual (new `version`)
  produces new ones, so nothing is silently overwritten.
* Only documents declared in `docs/source_manifest.json` are ingested
  (`backend.sources.manifest`) -- an unlisted file in `manual/` is an
  unknown document, not "probably the manual".
* `experiment_id` is attached only when the manifest already says which
  experiments a document covers. When a document spans several (the
  whole IACHY102 manual does), per-chunk attribution falls back to
  scanning the chunk's own text against `backend/scope/ontology.py`'s
  *strong* terms only -- the same discriminative vocabulary the query
  router uses, so a manual chunk and a question about it are tagged by
  the same rule. Weak/ambiguous chunks are left unattributed
  (`experiment_id=None`) rather than guessed, which is what keeps
  Experiment 3 chunks from leaking into an Experiment 7 answer merely
  for sharing the word "concentration" -- see brief §6.

Chunking is by page and by paragraph within a page, not by an arbitrary
token window: a paragraph is the unit a manual actually reasons in, and
splitting mid-paragraph would sever a formula from the sentence that
explains its symbols.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from backend.retrieval.chunks import Chunk, ContentType, make_chunk_id
from backend.retrieval.images import render_page_image, renderer_available
from backend.scope import ontology
from backend.sources.manifest import ManifestEntry, get_manifest
from backend.sources.tiers import SourceDocument

log = logging.getLogger(__name__)

MAX_CHUNK_CHARS = 900

#: Cues that a paragraph documents a GUI step rather than wet-lab
#: procedure or theory. Used only to set `content_type` for citation
#: phrasing -- never to decide *which* experiment a chunk belongs to.
_SOFTWARE_STEP_RE = re.compile(
    r"\b(?:click|select|open|choose|menu|tab|button|dialog|window|drop-?down|"
    r"checkbox|toolbar|icon|input file|output file|\.inp\b|\.out\b)\b",
    re.IGNORECASE,
)
_FORMULA_HINT_RE = re.compile(r"[=≈][^=]{0,80}(?:\d|[a-zA-Z]\s*\()")
_TABLE_HINT_RE = re.compile(r"\btable\s+\d", re.IGNORECASE)
_FIGURE_HINT_RE = re.compile(r"\b(?:figure|fig\.|screenshot)\s*\d", re.IGNORECASE)
_WORKED_EXAMPLE_RE = re.compile(r"\bworked\s+example\b|\bsample\s+calculation\b", re.IGNORECASE)


@dataclass(frozen=True)
class IngestReport:
    """What ingesting one document actually produced.

    Distinguishes three outcomes that a bare `list[Chunk]` would
    collapse: successfully ingested, declared-but-blocked (the file is
    absent), and declared-but-excluded (superseded or non-indexable).
    Only the first contributes chunks; the other two are still reported,
    because a pipeline that quietly indexes nothing must not look
    identical to one that is working -- see `docs/final_audit.md`.
    """

    document_id: str
    status: str  # "ingested" | "blocked" | "excluded"
    chunk_count: int = 0
    page_count: int = 0
    reason: str = ""
    chunks: tuple[Chunk, ...] = field(default_factory=tuple, repr=False)


def ingest_document(
    entry: ManifestEntry, *, image_output_dir: str | Path | None = None
) -> IngestReport:
    document = entry.document

    if entry.is_superseded:
        return IngestReport(
            document_id=document.document_id,
            status="excluded",
            reason=f"superseded by {entry.superseded_by}",
        )
    if not entry.indexable:
        return IngestReport(
            document_id=document.document_id, status="excluded", reason="marked non-indexable"
        )
    if not document.present:
        return IngestReport(
            document_id=document.document_id,
            status="blocked",
            reason=f"file not present: {document.filename}",
        )

    path = Path(document.filename)
    if not path.exists():
        return IngestReport(
            document_id=document.document_id,
            status="blocked",
            reason=f"manifest says present=true but file not found at {path}",
        )

    pages = _extract_units(path)
    if not pages:
        return IngestReport(
            document_id=document.document_id,
            status="blocked",
            reason="no extractable text (empty, corrupt, or image-only source)",
        )

    chunks: list[Chunk] = []
    for page_number, text, section, experiment_hint in pages:
        image = None
        # Page images only apply to an actual PDF; a Tier C markdown
        # corpus has no page to rasterise.
        if image_output_dir is not None and path.is_file() and path.suffix.lower() == ".pdf":
            image = render_page_image(
                path, page_number, document_id=document.document_id, output_dir=image_output_dir
            )
        chunks.extend(
            _chunk_page(
                text,
                page_number,
                document=document,
                entry=entry,
                image=image,
                section=section,
                experiment_hint=experiment_hint,
            )
        )

    return IngestReport(
        document_id=document.document_id,
        status="ingested",
        chunk_count=len(chunks),
        page_count=len(pages),
        chunks=tuple(chunks),
    )


def ingest_all(*, image_output_dir: str | Path | None = None) -> list[IngestReport]:
    """Ingest every manifest entry. Every entry is reported, ingested or not."""
    return [
        ingest_document(entry, image_output_dir=image_output_dir) for entry in get_manifest()
    ]


#: Recognised plain-text source extensions, for Tier B/C material that
#: is not a scanned manual (e.g. `knowledge/adjacent/`). Anything else
#: under a directory is skipped rather than guessed at.
_TEXT_EXTENSIONS = (".md", ".markdown", ".txt")


#: A curated file named e.g. `exp07_orca_troubleshooting.md` names its own
#: experiment unambiguously by convention. Matched against the filename
#: stem so a topic file with no distinctive vocabulary of its own (a
#: generic troubleshooting note, say) still attributes correctly instead
#: of falling through to the ambiguous vocabulary scan.
_FILENAME_EXPERIMENT_RE = re.compile(r"^exp(\d{2})[_-]")

#: The manual's own heading format (see `manual/IACHY102_manual.md`):
#: "## Experiment N — Title (p.X-Y)". Only headings matching
#: `_EXPERIMENT_HEADING_RE` are indexed as retrievable units -- front
#: matter (the assessed-experiment-set table) and the closing
#: worked-example summary table are navigational aids *about* the
#: manual, not answerable content, and were the concrete cause of a
#: real live bug: without this split, the whole multi-experiment file
#: collapsed into one page-1 unit, so that front-matter table (short,
#: term-dense) consistently outranked the real per-experiment section on
#: every query, and every citation said "p. 1" regardless of which
#: experiment was actually asked about. Verified live before this fix
#: (`answer_question("Nernst equation worked example")` top-ranked the
#: "## Summary: which experiments..." chunk over Experiment 1's own
#: section) and after (top-ranks Experiment 1's section at its real
#: page). Same fix, same reasoning `backend/rag/retrieval.py::
#: _chunk_markdown` already applies for the older diagnosis-pipeline
#: retrieval module -- this module never inherited it because the two
#: packages were built independently (see `backend/retrieval/
#: __init__.py`'s docstring).
_MD_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_EXPERIMENT_HEADING_RE = re.compile(r"^Experiment\s+(\d+)\b")
_MD_PAGE_RE = re.compile(r"p\.\s*(\d+)")


def _split_markdown_by_experiment_heading(
    text: str,
) -> list[tuple[int, str, str, str | None]] | None:
    """Returns one `(start_page, body, heading, exp_hint)` unit per
    "## Experiment N ..." heading, or `None` if the text has no such
    heading at all -- the signal to fall back to whole-file-as-one-unit,
    which is the correct (and unchanged) behaviour for a single-topic
    adjacent-knowledge file that was never meant to have this structure.
    """
    headings = list(_MD_HEADING_RE.finditer(text))
    matches = [(m, _EXPERIMENT_HEADING_RE.match(m.group(1))) for m in headings]
    if not any(exp_match for _, exp_match in matches):
        return None

    units: list[tuple[int, str, str, str | None]] = []
    for i, (heading_match, exp_match) in enumerate(matches):
        if exp_match is None:
            continue
        start = heading_match.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        body = text[start:end].strip()
        if not body:
            continue
        heading_text = heading_match.group(1)
        page_match = _MD_PAGE_RE.search(heading_text) or _MD_PAGE_RE.search(body[:200])
        page = int(page_match.group(1)) if page_match else 1
        units.append((page, body, heading_text, f"exp{int(exp_match.group(1)):02d}"))
    return units


def _extract_units(path: Path) -> list[tuple[int, str, str, str | None]]:
    """Extract `(unit_number, text, section, experiment_hint)` from any
    source kind.

    `unit_number` plays the role a PDF page number plays elsewhere in
    this module: it is what `Chunk.page` is set from, and for a
    non-paginated source (a markdown file) it is simply that file's
    position in a stable, sorted ordering -- stable so re-ingesting an
    unchanged directory reproduces the same chunk IDs.

    `experiment_hint` is filename-derived and takes priority over the
    ambiguous per-chunk vocabulary scan in `_attribute_experiment` -- see
    `_FILENAME_EXPERIMENT_RE`. It is always `None` for a PDF, which has no
    filename-per-topic convention to read.
    """
    if path.is_dir():
        return _extract_from_directory(path)
    if path.suffix.lower() == ".pdf":
        return _extract_from_pdf(path)
    if path.suffix.lower() in _TEXT_EXTENSIONS:
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            return []
        by_heading = _split_markdown_by_experiment_heading(text)
        if by_heading is not None:
            return by_heading
        return [(1, text, _section_title(path), _filename_experiment_hint(path))]

    log.error("Unrecognised source kind for ingestion: %s", path)
    return []


def _extract_from_pdf(path: Path) -> list[tuple[int, str, str, str | None]]:
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - dependency is pinned
        log.error("pypdf is not installed; ingestion cannot read %s", path)
        return []

    try:
        reader = PdfReader(str(path))
        pages: list[tuple[int, str, str, str | None]] = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                pages.append((page_number, text, "", None))
        return pages
    except Exception as exc:  # pragma: no cover - corrupt/locked PDF
        log.error("Failed to read %s: %s", path, exc)
        return []


#: Meta-documentation about a directory, not answerable content. Ingesting
#: a directory's own README would surface sentences like "this directory
#: is Tier C" as if they were an answer to a student's question.
_IGNORED_FILENAMES = frozenset({"readme.md", "readme.txt"})


def _extract_from_directory(directory: Path) -> list[tuple[int, str, str, str | None]]:
    files = sorted(
        p
        for p in directory.iterdir()
        if p.is_file()
        and p.suffix.lower() in _TEXT_EXTENSIONS
        and p.name.lower() not in _IGNORED_FILENAMES
    )
    units: list[tuple[int, str, str, str | None]] = []
    for index, file_path in enumerate(files, start=1):
        text = file_path.read_text(encoding="utf-8", errors="replace")
        if text.strip():
            units.append(
                (index, text, _section_title(file_path), _filename_experiment_hint(file_path))
            )
    return units


def _filename_experiment_hint(path: Path) -> str | None:
    match = _FILENAME_EXPERIMENT_RE.match(path.stem.lower())
    return f"exp{match.group(1)}" if match else None


def _section_title(path: Path) -> str:
    return path.stem.replace("_", " ").replace("-", " ").strip().title()


def _chunk_page(
    text: str,
    page: int,
    *,
    document: SourceDocument,
    entry: ManifestEntry,
    image,
    section: str = "",
    experiment_hint: str | None = None,
) -> list[Chunk]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    packed = _pack(paragraphs, MAX_CHUNK_CHARS)

    chunks: list[Chunk] = []
    for index, body in enumerate(packed):
        locator = f"p{page}#{index}"
        chunk_id = make_chunk_id(document.document_id, document.version, locator)
        experiment_id = _attribute_experiment(body, document, hint=experiment_hint)
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                text=body,
                document_id=document.document_id,
                document_title=document.title,
                tier=document.tier,
                source_version=document.version,
                section=section,
                page=page,
                content_type=_classify_content(body),
                experiment_id=experiment_id,
                image=image,
            )
        )
    return chunks


def _pack(paragraphs: list[str], max_chars: int) -> list[str]:
    chunks: list[str] = []
    buffer = ""
    for para in paragraphs:
        if buffer and len(buffer) + len(para) + 1 > max_chars:
            chunks.append(buffer.strip())
            buffer = para
        else:
            buffer = f"{buffer}\n{para}" if buffer else para
    if buffer.strip():
        chunks.append(buffer.strip())
    return chunks


def _classify_content(text: str) -> ContentType:
    if _WORKED_EXAMPLE_RE.search(text):
        return ContentType.WORKED_EXAMPLE
    if _TABLE_HINT_RE.search(text):
        return ContentType.TABLE
    if _FIGURE_HINT_RE.search(text):
        return ContentType.FIGURE_CAPTION
    if _SOFTWARE_STEP_RE.search(text):
        return ContentType.SOFTWARE_STEP
    if _FORMULA_HINT_RE.search(text):
        return ContentType.FORMULA
    return ContentType.GENERAL


def _attribute_experiment(
    text: str, document: SourceDocument, *, hint: str | None = None
) -> str | None:
    """Which experiment this chunk belongs to, if that is unambiguous.

    A document declared for exactly one experiment in the manifest is
    attributed to it outright. A filename-derived `hint` (see
    `_filename_experiment_hint`) is trusted next, when it names an
    experiment the document actually covers -- this is what lets a
    generic-sounding paragraph in `exp07_orca_troubleshooting.md`
    attribute correctly even though it contains none of experiment 7's
    distinctive vocabulary. Only once both are unavailable does per-chunk
    vocabulary scanning run, and only when exactly one experiment's
    strong/software vocabulary is present -- ties or silence are left
    unattributed rather than guessed.
    """
    if len(document.experiments) == 1:
        return document.experiments[0]

    if hint and (not document.experiments or hint in document.experiments):
        return hint

    lowered = text.lower()
    hits: set[str] = set()
    for topic in ontology.routable_topics():
        if topic.id not in document.experiments and document.experiments:
            continue
        vocabulary = topic.strong_terms | topic.software
        if any(_word_in(term, lowered) for term in vocabulary):
            hits.add(topic.id)

    if len(hits) == 1:
        return hits.pop()
    return None


def _word_in(term: str, lowered_text: str) -> bool:
    if " " in term:
        return term in lowered_text
    return re.search(rf"\b{re.escape(term)}\b", lowered_text) is not None


def render_all_page_images(output_dir: str | Path) -> dict[str, bool]:
    """Coverage summary: which manifest documents got real page images.

    Used by the coverage-report tooling (`docs/final_audit.md`) to
    show, per document, whether visual grounding is actually available or
    only architecturally supported.
    """
    return {
        entry.document_id: entry.visual and renderer_available() and entry.ingestible
        for entry in get_manifest()
    }
