"""Aggregate income tax validation harness.

Computes total federal individual income tax across CPS and compares
against PolicyEngine, TAXSIM, and Cosilico.
"""

from .harness import (
    compute_policyengine_aggregates,
    generate_comparison_report,
    run_aggregate_validation,
)

__all__ = [
    "run_aggregate_validation",
    "compute_policyengine_aggregates",
    "generate_comparison_report",
]
