"""Pure endpoint projection and semantic audits for packed Quake aliases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class AliasProjectionRecord:
    row: int
    token: int
    depth_q6: int
    horizontal_components_q6: tuple[int, int]
    vertical_components_q6: tuple[int, int]
    source_extent: tuple[int, int]
    observed_horizontal_q7: tuple[int, int]
    observed_vertical_q7: tuple[int, int]


@dataclass(frozen=True, slots=True)
class AliasProjectionIssue:
    row: int
    token: int
    kind: str
    axis: str
    observed_q7: tuple[int, int]
    coherent_q7: tuple[int, int] | None


@dataclass(frozen=True, slots=True)
class AliasProjectionAudit:
    records: int
    issues: tuple[AliasProjectionIssue, ...]

    @property
    def issue_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for issue in self.issues:
            counts[issue.kind] = counts.get(issue.kind, 0) + 1
        return counts


def project_component_q7(component: int, depth: int) -> int:
    """Match the packed quotient-times-six rounding without saturation."""

    if depth <= 0:
        raise ValueError("alias projection depth must be positive")
    projected = (abs(component) * 2048 // depth) * 6
    return -projected if component < 0 else projected


def coherent_axis_q7(
    first_component: int,
    last_component: int,
    depth: int,
    center_q7: int,
    screen_sign: int,
) -> tuple[int, int] | None:
    """Project both original endpoints or reject one saturated outside side."""

    if screen_sign not in (-1, 1):
        raise ValueError("alias projection screen sign must be -1 or 1")
    if depth <= 0:
        raise ValueError("alias projection depth must be positive")
    if (first_component <= -depth and last_component <= -depth) or (
        first_component >= depth and last_component >= depth
    ):
        return None
    return (
        center_q7 + screen_sign * project_component_q7(first_component, depth),
        center_q7 + screen_sign * project_component_q7(last_component, depth),
    )


def _has_pixel_center_coverage(edges_q7: tuple[int, int], limit: int) -> bool:
    first_q7, last_q7 = edges_q7
    first = (first_q7 + 63) >> 7
    last = (last_q7 - 64) >> 7
    return first < limit and last >= 0 and last >= first


def audit_alias_projections(
    records: Iterable[AliasProjectionRecord],
) -> AliasProjectionAudit:
    """Audit reported rectangles against endpoint geometry across many rows."""

    issues: list[AliasProjectionIssue] = []
    count = 0
    for record in records:
        count += 1
        coherent = (
            coherent_axis_q7(
                *record.horizontal_components_q6,
                record.depth_q6,
                8192,
                1,
            ),
            coherent_axis_q7(
                *record.vertical_components_q6,
                record.depth_q6,
                7168,
                -1,
            ),
        )
        observed = (
            record.observed_horizontal_q7,
            record.observed_vertical_q7,
        )
        for axis, axis_coherent, axis_observed, limit in zip(
            ("horizontal", "vertical"),
            coherent,
            observed,
            (128, 112),
            strict=True,
        ):
            if axis_coherent is None:
                if _has_pixel_center_coverage(axis_observed, limit):
                    issues.append(
                        AliasProjectionIssue(
                            record.row,
                            record.token,
                            "sameSidePhantom",
                            axis,
                            axis_observed,
                            None,
                        )
                    )
                continue
            observed_span = axis_observed[1] - axis_observed[0]
            coherent_span = axis_coherent[1] - axis_coherent[0]
            if observed_span != coherent_span:
                kind = "clampedSpan"
            elif axis_observed != axis_coherent:
                kind = "endpointPhase"
            else:
                continue
            issues.append(
                AliasProjectionIssue(
                    record.row,
                    record.token,
                    kind,
                    axis,
                    axis_observed,
                    axis_coherent,
                )
            )

        width, height = record.source_extent
        if width <= 0 or height <= 0:
            raise ValueError("alias source extents must be positive")
        horizontal_span = abs(
            record.observed_horizontal_q7[1] - record.observed_horizontal_q7[0]
        )
        vertical_span = abs(
            record.observed_vertical_q7[1] - record.observed_vertical_q7[0]
        )
        cross_error = abs(horizontal_span * height - vertical_span * width)
        quantization_tolerance = 12 * (width + height)
        if cross_error > quantization_tolerance:
            issues.append(
                AliasProjectionIssue(
                    record.row,
                    record.token,
                    "anisotropicSpan",
                    "both",
                    (
                        record.observed_horizontal_q7[1]
                        - record.observed_horizontal_q7[0],
                        record.observed_vertical_q7[1] - record.observed_vertical_q7[0],
                    ),
                    None,
                )
            )
    return AliasProjectionAudit(count, tuple(issues))
