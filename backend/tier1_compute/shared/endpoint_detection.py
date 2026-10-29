"""Checker type: endpoint-detection experiments.

Supports both endpoint geometries the manual uses:

* ``peak``         -- the endpoint is where a derivative-style response
                      is maximal (potentiometric dE/dV, for example).
                      Refined by parabolic interpolation across the three
                      points around the maximum, so the answer is not
                      quantised to whichever volume happened to be dosed.
* ``intersection`` -- the endpoint is where two linear branches cross
                      (conductometric titrations, where conductance falls
                      then rises). Both branches are fitted by least
                      squares and solved simultaneously.

The endpoint alone is often not the reported quantity, so a plugin may
supply ``derive`` to turn the endpoint into the manual's final value
(a normality, a percentage, a mass).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

from backend.tier1_compute.shared.base import Checker
from backend.tier1_compute.shared import signatures
from backend.tier1_compute.shared.types import SignatureHit, Tolerance

PEAK = "peak"
INTERSECTION = "intersection"


class NoEndpointError(ValueError):
    """Raised when the data admits no endpoint at all."""


def first_derivative(xs: np.ndarray, ys: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """dy/dx at the midpoint of each consecutive pair of readings.

    This is the manual's DeltaE/DeltaV against average volume table for a
    potentiometric titration. Pairs with no volume change are skipped (a
    repeated reading has no slope).
    """
    dx = np.diff(xs)
    keep = dx != 0
    mid = ((xs[:-1] + xs[1:]) / 2.0)[keep]
    slope = (np.diff(ys)[keep]) / dx[keep]
    return mid, slope


class EndpointDetectionChecker(Checker):
    """Locate an endpoint, optionally derive a final value, then compare.

    Args:
        x_key / y_key: the titrant-volume and response series.
        geometry: ``peak`` or ``intersection``.
        derive: optional ``(endpoint_x, inputs) -> final value``. Omit it
            when the endpoint volume *is* the reported quantity.
        min_points: minimum readings the method requires.
        max_increment: widest acceptable spacing between readings; wider
            than this triggers the coarse-increments signature.
        min_prominence: how far a peak must stand above baseline to count
            as resolved (``peak`` geometry only).
        min_span: minimum total variation in the response, below which
            the run is treated as flat (``intersection`` geometry only).
        min_branch_points: least-squares needs at least this many points
            on each branch (``intersection`` geometry only).
        series_transform: optional ``(x, y) -> (x', y')`` applied to the
            recorded readings before the endpoint is located, e.g.
            :func:`first_derivative` to turn an EMF-vs-volume S-curve into
            DeltaE/DeltaV against average volume. Range and spacing checks
            still use the raw volumes; peak prominence uses the transformed
            response.
    """

    def __init__(
        self,
        *,
        x_key: str,
        y_key: str,
        geometry: str,
        tolerance: Tolerance,
        derive: Callable[[float, dict[str, Any]], float] | None = None,
        extra_required: tuple[str, ...] = (),
        min_points: int = 5,
        max_increment: float | None = None,
        min_prominence: float | None = None,
        min_span: float | None = None,
        min_branch_points: int = 3,
        series_transform: Callable[
            [np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]
        ]
        | None = None,
        label: str = "",
    ) -> None:
        if geometry not in (PEAK, INTERSECTION):
            raise ValueError(f"geometry must be '{PEAK}' or '{INTERSECTION}'")
        super().__init__(
            required_inputs=(x_key, y_key) + tuple(extra_required),
            tolerance=tolerance,
            label=label,
        )
        self.x_key = x_key
        self.y_key = y_key
        self.geometry = geometry
        self._derive = derive
        self.min_points = min_points
        self.max_increment = max_increment
        self.min_prominence = min_prominence
        self.min_span = min_span
        self.min_branch_points = min_branch_points
        self._series_transform = series_transform

    # -- data access ------------------------------------------------------

    def _series(self, inputs: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
        xs = np.asarray([float(v) for v in inputs[self.x_key]], dtype=float)
        ys = np.asarray([float(v) for v in inputs[self.y_key]], dtype=float)
        order = np.argsort(xs)
        return xs[order], ys[order]

    def validate(self, inputs: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        for key in (self.x_key, self.y_key):
            value = inputs.get(key)
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
                errors.append(f"'{key}' must be a list of readings")
        if errors:
            return errors
        try:
            xs, ys = self._series(inputs)
        except (TypeError, ValueError):
            return ["Titration data contains a non-numeric entry"]
        if xs.size != ys.size:
            errors.append(
                f"'{self.x_key}' has {xs.size} entries but '{self.y_key}' has {ys.size}"
            )
        if xs.size < self.min_points:
            errors.append(
                f"Only {xs.size} readings recorded; this titration needs at least "
                f"{self.min_points}"
            )
        if np.any(xs < 0):
            errors.append(f"'{self.x_key}' contains a negative volume")
        return errors

    # -- endpoint geometry ------------------------------------------------

    def _response(self, inputs: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
        """The series the endpoint is located on (transformed if configured)."""
        xs, ys = self._series(inputs)
        if self._series_transform is not None:
            xs, ys = self._series_transform(xs, ys)
        return xs, ys

    def find_endpoint(self, inputs: dict[str, Any]) -> float:
        xs, ys = self._response(inputs)
        if self.geometry == PEAK:
            return _peak_endpoint(xs, ys)
        return _intersection_endpoint(xs, ys, self.min_branch_points)

    def compute_expected(self, inputs: dict[str, Any]) -> float:
        endpoint = self.find_endpoint(inputs)
        if self._derive is None:
            return endpoint
        return float(self._derive(endpoint, inputs))

    def extra_detail(self, inputs: dict[str, Any]) -> dict[str, Any]:
        try:
            return {"endpoint_x": self.find_endpoint(inputs), "geometry": self.geometry}
        except (ValueError, KeyError, TypeError):
            return {"geometry": self.geometry}

    # -- signatures -------------------------------------------------------

    def data_quality_signature(self, inputs: dict[str, Any]) -> SignatureHit | None:
        """Whether this run can support an endpoint claim at all.

        Checked before expected-vs-reported: a flat trace, an unresolved
        peak or increments too coarse to bracket the transition all mean
        the endpoint is not determinable, however plausible the number
        written on the record sheet.
        """
        xs, ys = self._series(inputs)
        rx, ry = self._response(inputs)

        if self.min_span is not None:
            hit = signatures.detect_flat_response(ry, self.min_span)
            if hit:
                return hit

        if self.geometry == PEAK and self.min_prominence is not None:
            hit = signatures.detect_unresolved_peak(rx, ry, self.min_prominence)
            if hit:
                return hit

        if self.max_increment is not None:
            hit = signatures.detect_coarse_increments(xs, self.max_increment)
            if hit:
                return hit

        try:
            endpoint = self.find_endpoint(inputs)
        except (ValueError, NoEndpointError):
            return SignatureHit(
                code="no_detectable_endpoint",
                detail=(
                    "No endpoint can be located in this data -- the response "
                    "never turns the way the procedure requires."
                ),
                evidence={"n_points": int(xs.size)},
            )

        return signatures.detect_endpoint_outside_range(xs, endpoint)

    def detect_signature(
        self, inputs: dict[str, Any], expected: float, reported: float
    ) -> SignatureHit | None:
        hit = signatures.detect_unit_scale_error(expected, reported, self.tolerance)
        if hit:
            return hit

        return signatures.detect_rounding_drift(expected, reported, self.tolerance)


# ---------------------------------------------------------------------------
# Geometry implementations
# ---------------------------------------------------------------------------


def _peak_endpoint(xs: np.ndarray, ys: np.ndarray) -> float:
    """x at the maximum, refined by fitting a parabola to its neighbours."""
    if xs.size < 3:
        raise NoEndpointError("need at least three points to locate a peak")
    i = int(np.argmax(ys))
    if i == 0 or i == xs.size - 1:
        # The maximum sits at an edge, so the true peak is outside the
        # measured window. Report the edge and let the range signature
        # explain it rather than inventing a refinement.
        return float(xs[i])

    x0, x1, x2 = float(xs[i - 1]), float(xs[i]), float(xs[i + 1])
    y0, y1, y2 = float(ys[i - 1]), float(ys[i]), float(ys[i + 1])
    denom = (x0 - x1) * (x0 - x2) * (x1 - x2)
    if denom == 0.0:
        return x1
    a = (x2 * (y1 - y0) + x1 * (y0 - y2) + x0 * (y2 - y1)) / denom
    b = (
        x2 * x2 * (y0 - y1) + x1 * x1 * (y2 - y0) + x0 * x0 * (y1 - y2)
    ) / denom
    if a == 0.0:
        return x1
    vertex = -b / (2 * a)
    # Refinement must stay inside the bracketing points; otherwise the
    # three points are not peak-shaped and the raw maximum is honest.
    if not (x0 <= vertex <= x2) or not math.isfinite(vertex):
        return x1
    return float(vertex)


def _intersection_endpoint(xs: np.ndarray, ys: np.ndarray, min_branch: int) -> float:
    """Split into two branches, fit each, return where the lines cross.

    The split point is chosen to minimise total residual error across
    every admissible split -- the same thing done by eye when drawing two
    straight portions through a conductometric plot.
    """
    n = xs.size
    if n < 2 * min_branch:
        raise NoEndpointError(
            f"need at least {2 * min_branch} points to fit two branches"
        )

    best: tuple[float, float] | None = None  # (sse, endpoint)
    for split in range(min_branch, n - min_branch + 1):
        lx, ly = xs[:split], ys[:split]
        rx, ry = xs[split:], ys[split:]
        if np.ptp(lx) == 0 or np.ptp(rx) == 0:
            continue
        try:
            left = signatures.least_squares_fit(lx, ly)
            right = signatures.least_squares_fit(rx, ry)
        except ValueError:
            continue
        if left.slope == right.slope:
            continue

        sse = float(
            np.sum((ly - (left.slope * lx + left.intercept)) ** 2)
            + np.sum((ry - (right.slope * rx + right.intercept)) ** 2)
        )
        endpoint = (right.intercept - left.intercept) / (left.slope - right.slope)
        if not math.isfinite(endpoint):
            continue
        if best is None or sse < best[0]:
            best = (sse, float(endpoint))

    if best is None:
        raise NoEndpointError("no admissible two-branch split found")
    return best[1]
