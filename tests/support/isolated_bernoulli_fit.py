"""Run one ``fit_bernoulli_cusum`` call in a child process and report it as JSON.

**Why a child process.** ADR-014 Amendment 2 section 0, defect 2: at
m=200,000 f=0 the pre-amendment two-sided fit rebuilt a 1,474-state lattice
as a 16.5-million-state one and died with ``Fatal Python error:
Segmentation fault`` inside ``scipy.sparse.linalg.spsolve`` (exit code 139).
A segfault inside the pytest process ends the whole run, so a red test at a
large baseline could take every other test's result with it. In a child
process the same defect becomes one clearly failing test ("the fit process
died with signal 11") and the run stays finite -- which the red phase
requires.

Usage from a test: :func:`fit_in_child`. The child builds its baseline from
two shared ``ScoringResult`` objects (one pass, one fail), which keeps a
300,000-observation baseline at well under a second (ADR-014 Decision 18
item 3: "Build each baseline with one shared ``ScoringResult``").
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from drift_caliper.baseline import BernoulliArmLattice

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _json_safe(value: object) -> object:
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return repr(value)


def _lattice(lattice: BernoulliArmLattice | None) -> list[int] | None:
    if lattice is None:
        return None
    return [
        lattice.denominator,
        lattice.reference_units,
        lattice.decision_interval_units,
    ]


def _run(request: dict[str, Any]) -> dict[str, Any]:
    from drift_caliper.baseline import fit_bernoulli_cusum
    from drift_caliper.errors import CaliperError
    from tests.support.binary_baselines import binary_baseline

    baseline, _ = binary_baseline(request["m"], request["f"])
    outcomes: list[dict[str, Any]] = []
    for target in request["targets"]:
        try:
            chart = fit_bernoulli_cusum(
                baseline,
                target_arl=target,
                detect_rate_multiple=request.get("multiple"),
                direction=request["direction"],
            )
        except CaliperError as error:
            outcomes.append(
                {
                    "ok": False,
                    "type": type(error).__name__,
                    "context": _json_safe(dict(error.context)),
                }
            )
            continue
        outcomes.append(
            {
                "ok": True,
                "direction": chart.direction,
                "requested_arl": chart.requested_arl,
                "achieved_arl": chart.achieved_arl,
                "expected_detection_arl": chart.expected_detection_arl,
                "expected_improvement_detection_arl": (
                    chart.expected_improvement_detection_arl
                ),
                "calibration_method": chart.calibration_method,
                "lattice_lower": _lattice(chart.lattice_lower),
                "lattice_upper": _lattice(chart.lattice_upper),
                "advisories": [[a.kind, a.boundary] for a in chart.advisories],
                "p_u": chart.p_u,
                "p_l": chart.p_l,
            }
        )
    return {"outcomes": outcomes}


def fit_in_child(
    *,
    m: int,
    f: int,
    direction: str,
    targets: list[float],
    multiple: float | None = None,
    timeout: float,
) -> list[dict[str, Any]]:
    """Fit once per target on one ``m``/``f`` baseline, in a child process.

    Returns one dict per target: ``{"ok": True, ...fields}`` or
    ``{"ok": False, "type": ..., "context": ...}``. A child that dies (a
    segfault, an uncaught non-``CaliperError``) raises ``AssertionError``
    carrying its exit status and stderr tail.
    """
    request = {
        "m": m,
        "f": f,
        "direction": direction,
        "targets": targets,
        "multiple": multiple,
    }
    completed = subprocess.run(  # noqa: S603 -- fixed argv: this interpreter, this module
        [
            sys.executable,
            "-X",
            "faulthandler",
            "-m",
            "tests.support.isolated_bernoulli_fit",
            json.dumps(request),
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"the fit process died (exit status {completed.returncode}) for "
            f"{request}; stderr tail:\n{completed.stderr[-2000:]}"
        )
    result: dict[str, Any] = json.loads(completed.stdout.strip().splitlines()[-1])
    outcomes: list[dict[str, Any]] = result["outcomes"]
    return outcomes


if __name__ == "__main__":
    print(json.dumps(_run(json.loads(sys.argv[1]))))
