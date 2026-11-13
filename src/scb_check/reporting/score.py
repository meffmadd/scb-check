"""Compose data-only snapshot reports and serialize them to plain mappings."""

from collections.abc import Mapping
from math import isfinite
from types import MappingProxyType

from scb_check.metrics.ca import AfferentCoupling
from scb_check.metrics.callers import DistinctCallers
from scb_check.metrics.categories import category_dependencies
from scb_check.metrics.cbo import CBO
from scb_check.metrics.ce import EfferentCoupling
from scb_check.metrics.cic import CIC
from scb_check.metrics.cog_erosion import CognitiveErosion
from scb_check.metrics.dac import DAC
from scb_check.metrics.erosion import Erosion
from scb_check.metrics.module_dependencies import ModuleCallDependencies
from scb_check.metrics.mpc import MPC
from scb_check.metrics.rfc import RFC
from scb_check.metrics.ric import RIC
from scb_check.metrics.syntax import Syntax
from scb_check.metrics.units import Unit
from scb_check.metrics.verbosity import Verbosity
from scb_check.models import AnalysisResult
from scb_check.models import Report
from scb_check.models import ReportValue

# Explicit presentation/schema composition, not a metric dispatcher.
REPORT_UNITS: Mapping[str, Mapping[str, Unit]] = MappingProxyType(
    {
        "verbosity": Verbosity.units,
        "erosion": Erosion.units,
        "cog_erosion": CognitiveErosion.units,
        "syntax": Syntax.units,
        "cbo": CBO.units,
        "rfc": RFC.units,
        "mpc": MPC.units,
        "callers": DistinctCallers.units,
        "dac": DAC.units,
        "cic": CIC.units,
        "ric": RIC.units,
        "ca": AfferentCoupling.units,
        "ce": EfferentCoupling.units,
        "module_call_dependencies": ModuleCallDependencies.units,
    }
)


def report_unit(group: str, field: str) -> Unit:
    """Look up metric-owned units, including dotted per-language syntax fields."""
    return REPORT_UNITS[group][field.rsplit(".", 1)[-1] if group == "syntax" else field]


def compute_report(analysis: AnalysisResult) -> Report:
    """Calculate explicitly composed metrics from extracted facts, without IO."""
    flags = analysis.flags
    findings = flags.findings
    dependencies = category_dependencies(analysis.project)
    return MappingProxyType(
        {
            "verbosity": Verbosity().compute(
                flags.lines, findings.structural_findings
            ),
            "erosion": Erosion().compute(
                findings.all_functions, findings.high_cc_functions
            ),
            "cog_erosion": CognitiveErosion().compute(
                findings.all_functions, findings.high_cog_functions
            ),
            "syntax": Syntax().compute(flags.syntax_by_language),
            "cbo": CBO().compute(analysis.project.modules),
            "rfc": RFC().compute(analysis.project),
            "mpc": MPC().compute(analysis.project.modules),
            "callers": DistinctCallers().compute(analysis.project.modules),
            "dac": DAC().compute(analysis.project.modules),
            "cic": CIC().compute(analysis.project.modules),
            "ric": RIC().compute(analysis.project.modules),
            "ca": AfferentCoupling().compute(dependencies),
            "ce": EfferentCoupling().compute(dependencies),
            "module_call_dependencies": ModuleCallDependencies().compute(analysis.project.modules),
        }
    )


def serialize_report(report: Report) -> dict[str, dict[str, ReportValue]]:
    """Return fresh JSON-compatible dictionaries, independent of `report`."""
    validate_report(report)
    return {group: dict(result) for group, result in report.items()}


def validate_report(report: Report) -> None:
    """Reject incomplete or nonnumerical reports at public reporting boundaries."""
    if missing := REPORT_UNITS.keys() - report.keys():
        raise ValueError(f"missing required metric groups: {sorted(missing)!r}")
    for group, result in report.items():
        if not isinstance(result, Mapping):
            raise TypeError(f"metric {group!r} must be a flat mapping")
        if missing := REPORT_UNITS.get(group, {}).keys() - result.keys():
            raise ValueError(
                f"missing required fields in {group!r}: {sorted(missing)!r}"
            )
        for field, value in result.items():
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or (isinstance(value, float) and not isfinite(value))
            ):
                raise ValueError(
                    f"{group}.{field} must be a finite number or None, got {value!r}"
                )
