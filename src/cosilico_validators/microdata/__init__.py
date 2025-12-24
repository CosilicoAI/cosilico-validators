"""Microdata adapters for tax/benefit validation.

This module provides a unified interface for working with microdata
from different sources (PolicyEngine, TAXSIM, raw CPS, etc.) and
calculating variables using different engines (Cosilico, PE, TAXSIM).

Key abstractions:
- MicrodataSource: Provides input data and entity structure
- Calculator: Computes tax/benefit variables on microdata
- EntityIndex: Maps relationships between entity levels

Usage:
    from cosilico_validators.microdata import (
        MicrodataValidator,
        PolicyEngineMicrodataSource,
        CosilicoCalculator,
    )

    # Simple validation
    validator = MicrodataValidator()
    report = validator.run(variables=["eitc", "niit"])

    # Custom setup
    source = PolicyEngineMicrodataSource(year=2024)
    cosilico = CosilicoCalculator()
    result = cosilico.calculate("net_investment_income_tax", source)
"""

from .base import (
    MicrodataSource,
    Calculator,
    EntityIndex,
    CalculationResult,
    ComparisonResult,
    compare_calculators,
)
from .policyengine import PolicyEngineMicrodataSource, PolicyEngineCalculator
from .cosilico import CosilicoCalculator
from .taxsim import TAXSIMCalculator
from .runner import MicrodataValidator, ValidationReport, run_validation

__all__ = [
    # Base classes
    "MicrodataSource",
    "Calculator",
    "EntityIndex",
    "CalculationResult",
    "ComparisonResult",
    "compare_calculators",
    # Sources
    "PolicyEngineMicrodataSource",
    # Calculators
    "PolicyEngineCalculator",
    "CosilicoCalculator",
    "TAXSIMCalculator",
    # Runner
    "MicrodataValidator",
    "ValidationReport",
    "run_validation",
]
