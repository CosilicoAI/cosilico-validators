"""TaxSim 35 validation infrastructure for Cosilico.

This module provides tools for validating Cosilico tax calculations
against NBER's TaxSim 35 web API.
"""

from .taxsim_client import TaxSimClient, TaxSimCase, TaxSimResult
from .taxsim_comparison import TaxSimComparison, ComparisonResult
from .variable_mapping import (
    TAXSIM_TO_COSILICO,
    COSILICO_TO_TAXSIM,
    map_taxsim_to_cosilico,
    map_cosilico_to_taxsim,
)

__all__ = [
    "TaxSimClient",
    "TaxSimCase",
    "TaxSimResult",
    "TaxSimComparison",
    "ComparisonResult",
    "TAXSIM_TO_COSILICO",
    "COSILICO_TO_TAXSIM",
    "map_taxsim_to_cosilico",
    "map_cosilico_to_taxsim",
]
