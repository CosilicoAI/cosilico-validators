"""Cosilico Validators - Multi-system tax/benefit validation."""

from cosilico_validators.consensus import ConsensusEngine, ValidationResult
from cosilico_validators.consensus.engine import ConsensusLevel
from cosilico_validators.validators.base import (
    BaseValidator,
    TestCase,
    ValidatorResult,
    ValidatorType,
)

# Validation-driven encoding infrastructure
from cosilico_validators.plugin_history import (
    PluginHistoryTools,
    FailureSummary,
    SuggestionOutcome,
    get_history_tools,
)
from cosilico_validators.failure_diagnosis import (
    FailureDiagnosis,
    DiagnosisLayer,
    LayerDiagnosis,
    diagnose_encoding_failure,
)
from cosilico_validators.adaptive_validator import (
    AdaptiveValidator,
    PluginArm,
    SamplePlan,
    get_adaptive_validator,
)
from cosilico_validators.improvement_decisions import (
    ImprovementDecision,
    ImprovementOption,
    ImprovementForecast,
    ImprovementDecisionLog,
    create_improvement_decision,
    get_decision_log,
)
from cosilico_validators.encoding_orchestrator import (
    EncodingOrchestrator,
    EncodingSession,
    encode_variable,
    AGI_TEST_CASES,
    EARNED_INCOME_TEST_CASES,
    EITC_TEST_CASES,
)

__version__ = "0.1.0"
__all__ = [
    # Consensus validation
    "ConsensusEngine",
    "ConsensusLevel",
    "ValidationResult",
    "BaseValidator",
    "TestCase",
    "ValidatorResult",
    "ValidatorType",
    # Plugin history tools
    "PluginHistoryTools",
    "FailureSummary",
    "SuggestionOutcome",
    "get_history_tools",
    # Failure diagnosis
    "FailureDiagnosis",
    "DiagnosisLayer",
    "LayerDiagnosis",
    "diagnose_encoding_failure",
    # Adaptive validation
    "AdaptiveValidator",
    "PluginArm",
    "SamplePlan",
    "get_adaptive_validator",
    # Improvement decisions
    "ImprovementDecision",
    "ImprovementOption",
    "ImprovementForecast",
    "ImprovementDecisionLog",
    "create_improvement_decision",
    "get_decision_log",
    # Encoding orchestrator
    "EncodingOrchestrator",
    "EncodingSession",
    "encode_variable",
    "AGI_TEST_CASES",
    "EARNED_INCOME_TEST_CASES",
    "EITC_TEST_CASES",
]
