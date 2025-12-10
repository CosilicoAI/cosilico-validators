"""Cosilico Validators - Multi-system tax/benefit validation."""

from cosilico_validators.consensus import ConsensusEngine, ValidationResult
from cosilico_validators.consensus.engine import ConsensusLevel
from cosilico_validators.validators.base import (
    BaseValidator,
    TestCase,
    ValidatorResult,
    ValidatorType,
)

__version__ = "0.1.0"
__all__ = [
    "ConsensusEngine",
    "ConsensusLevel",
    "ValidationResult",
    "BaseValidator",
    "TestCase",
    "ValidatorResult",
    "ValidatorType",
]
