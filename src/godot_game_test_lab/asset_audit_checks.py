from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from .asset_audit_contract import AuditDocument, AuditRow
from .asset_audit_io import AssetAuditError, GitState, portable_path_key
from .asset_audit_png import ImageProbe


@dataclass
class FindingCollector:
    maximum: int

    def __post_init__(self) -> None:
        if self.maximum < 1:
            raise AssetAuditError("maximum_findings must be positive")
        self.items: list[dict[str, Any]] = []
        self.code_counts: Counter[str] = Counter()
        self.error_count = 0
        self.warning_count = 0
        self.omitted_count = 0

    def add(
        self,
        code: str,
        severity: str,
        message: str,
        *,
        path: str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        if severity not in {"error", "warning"}:
            raise AssetAuditError(f"Unsupported finding severity: {severity}")
        self.code_counts[code] += 1
        if severity == "error":
            self.error_count += 1
        else:
            self.warning_count += 1
        if len(self.items) >= self.maximum:
            self.omitted_count += 1
            return
        finding: dict[str, Any] = {
            "code": code,
            "severity": severity,
            "message": message,
        }
        if path is not None:
            finding["path"] = path
        if evidence:
            finding["evidence"] = evidence
        self.items.append(finding)

    def payload(self) -> list[dict[str, Any]]:
        return list(self.items)


@dataclass(frozen=True)
class ObservedAsset:
    row: AuditRow
    size_bytes: int
    sha256: str
    probe: ImageProbe | None


def _state_unchanged(before: GitState, after: GitState) -> bool:
    return before == after


def _known_number(value: int | float | None) -> int | float | None:
    return value if value is not None else None


def _compare_image_evidence(
    row: AuditRow,
    probe: ImageProbe,
    findings: FindingCollector,
    *,
    allow_unverified_alpha: bool,
) -> None:
    image = row.image
    if image is None:
        if row.transparency_policy == "require-meaningful-alpha":
            findings.add(
                "alpha-evidence-missing",
                "error",
                "Alpha-required asset has no Art Studio image evidence.",
                path=row.path,
            )
        return

    if not probe.valid:
        findings.add(
            "invalid-image-payload",
            "error",
            "The current image bytes are malformed or unsupported by their declared format.",
            path=row.path,
            evidence={"format": probe.format, "warnings": list(probe.warnings)},
        )
        return

    comparisons = (
        ("format", image.format.casefold(), probe.format.casefold()),
        ("width", _known_number(image.width), _known_number(probe.width)),
        ("height", _known_number(image.height), _known_number(probe.height)),
        ("bitDepth", image.bit_depth, probe.bit_depth),
        ("colourModel", image.colour_model, probe.colour_model),
        ("hasAlphaChannel", image.has_alpha_channel, probe.has_alpha_channel),
    )
    disagreements: dict[str, dict[str, Any]] = {}
    for label, audited, observed in comparisons:
        if observed is not None and audited != observed:
            disagreements[label] = {"audited": audited, "observed": observed}
    if image.probe_complete != probe.probe_complete:
        disagreements["probeComplete"] = {
            "audited": image.probe_complete,
            "observed": probe.probe_complete,
        }
    if disagreements:
        findings.add(
            "audit-image-evidence-disagrees",
            "error",
            "Independent image evidence disagrees with the Art Studio audit.",
            path=row.path,
            evidence=disagreements,
        )

    if not probe.probe_complete:
        findings.add(
            "image-runtime-verification-required",
            "warning",
            "The bounded source probe cannot establish final decoded image evidence.",
            path=row.path,
            evidence={"format": probe.format, "warnings": list(probe.warnings)},
        )

    if probe.probe_complete and image.alpha_usage != probe.alpha_usage:
        findings.add(
            "audit-alpha-disagrees",
            "error",
            "Independent decoded alpha disagrees with the Art Studio audit.",
            path=row.path,
            evidence={
                "auditedAlpha": image.alpha_usage,
                "observedAlpha": probe.alpha_usage,
            },
        )

    if probe.alpha_usage == "fully-transparent":
        findings.add(
            "fully-transparent-image",
            "error",
            "The image contains no visible subject pixels.",
            path=row.path,
        )

    if (
        row.transparency_policy == "preserve-authored-opaque"
        and probe.alpha_usage in {"meaningful", "fully-transparent"}
    ):
        findings.add(
            "opaque-plate-transparency-review",
            "warning",
            "This full-plate role ordinarily remains opaque; confirm transparency is intentional.",
            path=row.path,
        )
    if (
        row.transparency_policy == "preserve-authored-black-stage"
        and probe.alpha_usage == "meaningful"
    ):
        findings.add(
            "black-stage-transparency-review",
            "warning",
            "Dialogue close-ups ordinarily retain their authored presentation stage.",
            path=row.path,
        )

    if row.transparency_policy == "require-meaningful-alpha":
        if probe.alpha_usage == "meaningful":
            return
        if probe.alpha_usage == "unknown" and allow_unverified_alpha:
            findings.add(
                "alpha-runtime-verification-required",
                "warning",
                "Meaningful alpha remains unproven and requires decoded runtime evidence.",
                path=row.path,
                evidence={"warnings": list(probe.warnings)},
            )
            return
        findings.add(
            "meaningful-alpha-not-proven",
            "error",
            (
                "This role requires meaningful transparency and the independent "
                "probe did not prove it."
            ),
            path=row.path,
            evidence={
                "auditedAlpha": image.alpha_usage,
                "observedAlpha": probe.alpha_usage,
                "warnings": list(probe.warnings),
            },
        )


def _independent_animation_dimensions(
    audit: AuditDocument,
    observed: dict[str, ObservedAsset],
    findings: FindingCollector,
) -> None:
    for family in audit.animation_families:
        dimensions: list[tuple[int | float, int | float]] = []
        unknown = False
        for frame in family.frames:
            asset = observed.get(frame.path)
            probe = asset.probe if asset is not None else None
            if probe is None or probe.width is None or probe.height is None:
                unknown = True
                continue
            dimensions.append((probe.width, probe.height))
        actual: bool | str
        if unknown or len(dimensions) != len(family.frames):
            actual = "unknown"
        else:
            actual = len(set(dimensions)) == 1
        if family.consistent_dimensions != actual:
            findings.add(
                "animation-canvas-evidence-disagrees",
                "error",
                "Independent frame dimensions disagree with the Art Studio animation family.",
                evidence={
                    "familyId": family.id,
                    "audited": family.consistent_dimensions,
                    "observed": actual,
                    "dimensions": [list(value) for value in dimensions[:100]],
                },
            )
        if actual is False:
            findings.add(
                "animation-canvas-mismatch",
                "error",
                "Animation frames use inconsistent canvases.",
                evidence={"familyId": family.id},
            )


def _duplicate_cleanup_contract(
    audit: AuditDocument,
    findings: FindingCollector,
) -> None:
    expected_duplicates = {
        portable_path_key(path)
        for group in audit.duplicate_groups
        for path in group.paths
        if path != group.canonical_path
    }
    declared_duplicates = {
        portable_path_key(candidate.path)
        for candidate in audit.cleanup_candidates
        if candidate.action == "review-exact-duplicate"
    }
    if expected_duplicates != declared_duplicates:
        findings.add(
            "duplicate-cleanup-candidates-incomplete",
            "error",
            "Exact duplicate cleanup candidates do not match the declared duplicate groups.",
            evidence={
                "missing": sorted(expected_duplicates - declared_duplicates)[:100],
                "unexpected": sorted(declared_duplicates - expected_duplicates)[:100],
            },
        )

    rows = {portable_path_key(row.path): row for row in audit.art_files}
    for candidate in audit.cleanup_candidates:
        if candidate.action != "review-unreferenced-runtime":
            continue
        row = rows[portable_path_key(candidate.path)]
        if row.reference_count != 0 or row.category not in {"image", "animation"}:
            findings.add(
                "invalid-unreferenced-cleanup-candidate",
                "error",
                "Unreferenced cleanup candidate is not an unreferenced runtime media row.",
                path=candidate.path,
                evidence={
                    "referenceCount": row.reference_count,
                    "category": row.category,
                },
            )
