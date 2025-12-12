"""Base validator interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class ValidatorType(Enum):
    """Types of validators by authority level."""

    PRIMARY = "primary"  # TaxAct - ground truth
    REFERENCE = "reference"  # PolicyEngine, TAXSIM - high coverage
    SUPPLEMENTARY = "supplementary"  # PSL, Atlanta Fed PRD - additional signal


@dataclass
class TestCase:
    """A single test case for validation."""

    name: str
    inputs: Dict[str, Any]
    expected: Dict[str, float]
    citation: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class ValidatorResult:
    """Result from a single validator."""

    validator_name: str
    validator_type: ValidatorType
    calculated_value: Optional[float]
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.calculated_value is not None and self.error is None


class BaseValidator(ABC):
    """Base class for all tax/benefit validators."""

    name: str
    validator_type: ValidatorType
    supported_variables: Set[str]

    @abstractmethod
    def validate(
        self, test_case: TestCase, variable: str, year: int = 2024
    ) -> ValidatorResult:
        """Run a test case and return the calculated value.

        Args:
            test_case: The test case with inputs and expected outputs
            variable: The variable to calculate (e.g., "eitc", "ctc")
            year: Tax year

        Returns:
            ValidatorResult with calculated value or error
        """
        pass

    @abstractmethod
    def supports_variable(self, variable: str) -> bool:
        """Check if this validator supports a given variable."""
        pass

    def batch_validate(
        self, test_cases: List[TestCase], variable: str, year: int = 2024
    ) -> List[ValidatorResult]:
        """Validate multiple test cases.

        Default implementation calls validate() sequentially.
        Subclasses can override for batch optimization.
        """
        return [self.validate(tc, variable, year) for tc in test_cases]
