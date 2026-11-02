"""Loading and validating `docs/source_manifest.json`.

Nothing is ingested unless it is declared in the manifest. That is the
mechanism that keeps the tiers from mixing: a file that appears in
`manual/` without a manifest entry is not "probably the manual", it is
an unknown document, and the ingester refuses it.
"""

from __future__ import annotations

import functools
import json
from dataclasses import dataclass
from pathlib import Path

from backend.sources.tiers import SourceDocument, SourceTier

#: Roles the manifest may declare. Kept closed so a typo becomes an error
#: rather than a new, silently unhandled category of material.
KNOWN_ROLES: frozenset[str] = frozenset(
    {
        "official_manual",
        "student_script",
        "professor_script",
        "supplementary_material",
        "generated_test_material",
    }
)

#: Roles whose material must never be reachable by student-facing
#: retrieval, whatever tier they are declared at.
_NEVER_STUDENT_FACING: frozenset[str] = frozenset({"generated_test_material"})


class ManifestError(ValueError):
    """The manifest is malformed, or declares something incoherent."""


@dataclass(frozen=True)
class ManifestEntry:
    document: SourceDocument
    role: str
    visual: bool
    indexable: bool
    superseded_by: str | None

    @property
    def document_id(self) -> str:
        return self.document.document_id

    @property
    def tier(self) -> SourceTier:
        return self.document.tier

    @property
    def is_superseded(self) -> bool:
        return self.superseded_by is not None

    @property
    def ingestible(self) -> bool:
        """Whether ingestion should attempt to read this at all.

        Absent, superseded and non-indexable documents are all reported
        rather than skipped -- a blocked source is information, and a
        pipeline that quietly indexes nothing looks identical to one that
        is working.
        """
        return (
            self.document.present
            and self.indexable
            and not self.is_superseded
            and self.role not in _NEVER_STUDENT_FACING
        )


@dataclass(frozen=True)
class Manifest:
    entries: tuple[ManifestEntry, ...]
    manifest_version: str
    updated: str

    def __iter__(self):
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def by_id(self, document_id: str) -> ManifestEntry:
        for entry in self.entries:
            if entry.document_id == document_id:
                return entry
        raise KeyError(f"No manifest entry for document '{document_id}'")

    def ingestible(self) -> list[ManifestEntry]:
        return [e for e in self.entries if e.ingestible]

    def blocked(self) -> list[ManifestEntry]:
        """Declared sources that cannot currently be ingested, with reasons."""
        return [e for e in self.entries if not e.ingestible and self._is_blocking(e)]

    @staticmethod
    def _is_blocking(entry: ManifestEntry) -> bool:
        # Superseded and test material are *intentionally* not ingested;
        # they are not blockers, they are exclusions.
        return not entry.document.present and not entry.is_superseded

def manifest_path() -> Path:
    return Path(__file__).resolve().parents[2] / "docs" / "source_manifest.json"


def load_manifest(path: str | Path | None = None) -> Manifest:
    """Parse and validate the manifest. Raises rather than degrading."""
    target = Path(path) if path is not None else manifest_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestError(f"Source manifest not found at {target}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"Source manifest at {target} is not valid JSON: {exc}") from exc

    documents = raw.get("documents")
    if not isinstance(documents, list) or not documents:
        raise ManifestError("Source manifest declares no documents")

    entries: list[ManifestEntry] = []
    seen: set[str] = set()
    for index, item in enumerate(documents):
        entry = _parse_entry(item, index)
        if entry.document_id in seen:
            raise ManifestError(f"Duplicate document_id '{entry.document_id}'")
        seen.add(entry.document_id)
        entries.append(entry)

    for entry in entries:
        if entry.superseded_by and entry.superseded_by not in seen:
            raise ManifestError(
                f"{entry.document_id} is superseded by '{entry.superseded_by}', "
                "which is not declared in the manifest"
            )

    _assert_single_current_manual(entries)

    return Manifest(
        entries=tuple(entries),
        manifest_version=str(raw.get("manifest_version", "")),
        updated=str(raw.get("updated", "")),
    )


def _parse_entry(item: object, index: int) -> ManifestEntry:
    if not isinstance(item, dict):
        raise ManifestError(f"Manifest document #{index} is not an object")

    where = item.get("document_id") or f"#{index}"

    for required in ("document_id", "tier", "role", "filename", "title", "version"):
        if not item.get(required):
            raise ManifestError(f"Manifest document {where} is missing '{required}'")

    role = str(item["role"])
    if role not in KNOWN_ROLES:
        raise ManifestError(
            f"Manifest document {where} declares unknown role '{role}'. "
            f"Known roles: {sorted(KNOWN_ROLES)}. Add the role deliberately "
            "rather than letting a typo create a new category of material."
        )

    try:
        tier = SourceTier(str(item["tier"]))
    except ValueError as exc:
        raise ManifestError(
            f"Manifest document {where} declares unknown tier '{item['tier']}'"
        ) from exc

    document = SourceDocument(
        document_id=str(item["document_id"]),
        tier=tier,
        filename=str(item["filename"]),
        title=str(item["title"]),
        version=str(item["version"]),
        experiments=tuple(item.get("experiments") or ()),
        present=bool(item.get("present", False)),
        notes=str(item.get("notes", "")),
    )

    return ManifestEntry(
        document=document,
        role=role,
        visual=bool(item.get("visual", False)),
        indexable=bool(item.get("indexable", True)),
        superseded_by=(str(item["superseded_by"]) if item.get("superseded_by") else None),
    )


def _assert_single_current_manual(entries: list[ManifestEntry]) -> None:
    """Exactly one Tier A manual may be current.

    Two current manuals is the specific failure this whole phase exists
    to correct: the repository spent two sessions answering from BACHY105
    while IACHY102 was the assessed course.
    """
    current = [
        e
        for e in entries
        if e.role == "official_manual" and not e.is_superseded
    ]
    if len(current) != 1:
        raise ManifestError(
            "Exactly one official_manual must be current (not superseded); "
            f"found {len(current)}: {[e.document_id for e in current]}. "
            "If a new manual replaces an old one, mark the old one "
            "'superseded_by' rather than deleting it, so a stray copy is "
            "recognised and refused."
        )


@functools.lru_cache
def get_manifest() -> Manifest:
    return load_manifest()


def current_manual() -> ManifestEntry:
    """The one Tier A manual that is current. Always exists after validation."""
    for entry in get_manifest():
        if entry.role == "official_manual" and not entry.is_superseded:
            return entry
    raise ManifestError("no current official manual")  # pragma: no cover
