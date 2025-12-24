"""Multi-Layer Failure Diagnosis - identifies which layer caused an encoding failure.

When encoding fails validation, the root cause could be in any of 6 layers:
1. Plugin (cosilico-claude) - Instructions, subagents, prompts
2. DSL Core (cosilico-engine) - DSL can't express the required logic
3. Parameters (cosilico-data-sources) - Missing or incorrect parameter values
4. Test Cases (cosilico-validators) - Test case itself is wrong
5. Validators (PolicyEngine/TAXSIM) - Bug in validation systems
6. Variable Schema (cosilico-us) - Missing input variable definition

This module diagnoses failures to determine where fixes should be made.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from .consensus.engine import ConsensusLevel, ValidationResult
from .encoding_validator import EncodingValidationResult, ValidationStatus


class DiagnosisLayer(Enum):
    """The layer where a failure originated."""

    PLUGIN = "plugin"  # Instructions/prompts need improvement
    DSL_CORE = "dsl_core"  # DSL needs new feature
    PARAMETERS = "parameters"  # Missing or incorrect parameters
    TEST_CASE = "test_case"  # Test case is incorrect
    VALIDATOR = "validator"  # PE/TAXSIM has a bug
    VARIABLE_SCHEMA = "variable_schema"  # Missing input variable


@dataclass
class LayerDiagnosis:
    """Diagnosis result for a failure."""

    layer: DiagnosisLayer
    confidence: float  # 0-1 confidence in this diagnosis
    explanation: str
    suggested_fix: str
    evidence: list[str] = field(default_factory=list)
    alternative_layers: list[DiagnosisLayer] = field(default_factory=list)


@dataclass
class DiagnosisContext:
    """Context needed for diagnosis."""

    variable: str
    validation_result: EncodingValidationResult
    test_case_inputs: dict[str, Any]
    test_case_expected: dict[str, Any]
    error_messages: list[str] = field(default_factory=list)
    validator_outputs: dict[str, float] = field(default_factory=dict)


class FailureDiagnosis:
    """Diagnoses encoding failures to identify root cause layer.

    Uses a decision tree approach based on failure patterns:
    - Validators disagree → likely validator bug
    - Missing variable error → variable schema
    - Missing parameter error → parameters
    - DSL syntax/capability error → DSL core
    - Test case has suspicious values → test case
    - None of the above → plugin needs improvement
    """

    # Known DSL limitations (patterns that DSL can't express yet)
    DSL_LIMITATIONS = [
        "phase_out_cliff",  # Cliff phase-outs not well supported
        "married_filing_separately_different_rules",  # Complex MFS logic
        "state_specific_override",  # State-federal interactions
        "prior_year_income",  # Multi-year calculations
        "recapture",  # Tax recapture provisions
    ]

    # Common test case errors
    SUSPICIOUS_TEST_VALUES = [
        (-1, "Negative value in expected output"),
        (1e10, "Unrealistically large value"),
        (0.001, "Suspiciously small non-zero value"),
    ]

    def diagnose(self, context: DiagnosisContext) -> LayerDiagnosis:
        """Diagnose the root cause of an encoding failure.

        Args:
            context: Failure context with validation results and errors

        Returns:
            LayerDiagnosis with identified layer and suggested fix
        """
        # Check validators first - if they disagree, might be upstream bug
        validator_diagnosis = self._check_validator_disagreement(context)
        if validator_diagnosis:
            return validator_diagnosis

        # Check for missing input variable
        schema_diagnosis = self._check_missing_variable(context)
        if schema_diagnosis:
            return schema_diagnosis

        # Check for missing parameters
        param_diagnosis = self._check_missing_parameter(context)
        if param_diagnosis:
            return param_diagnosis

        # Check for DSL limitations
        dsl_diagnosis = self._check_dsl_limitation(context)
        if dsl_diagnosis:
            return dsl_diagnosis

        # Check for suspicious test case
        test_diagnosis = self._check_suspicious_test(context)
        if test_diagnosis:
            return test_diagnosis

        # Default: plugin needs improvement
        return self._plugin_diagnosis(context)

    def _check_validator_disagreement(self, context: DiagnosisContext) -> Optional[LayerDiagnosis]:
        """Check if validators disagree (potential upstream bug)."""
        results = context.validation_result.consensus_results

        if not results:
            return None

        # Find results where validators disagree
        disagreements = [
            r for r in results
            if r.consensus_level == ConsensusLevel.DISAGREEMENT
        ]

        if not disagreements:
            return None

        # Check if validators give very different values
        for result in disagreements:
            values = [
                r.calculated_value
                for r in result.validator_results.values()
                if r.calculated_value is not None
            ]

            if len(values) < 2:
                continue

            # Check for significant disagreement (>10% relative difference)
            max_val = max(values)
            min_val = min(values)
            if max_val > 0 and (max_val - min_val) / max_val > 0.1:
                return LayerDiagnosis(
                    layer=DiagnosisLayer.VALIDATOR,
                    confidence=0.7,
                    explanation=f"Validators disagree significantly: {min_val:.0f} vs {max_val:.0f}",
                    suggested_fix="Investigate which validator is correct. File upstream bug if needed.",
                    evidence=[
                        f"PolicyEngine: {values[0]:.0f}" if values else "N/A",
                        f"Value spread: {max_val - min_val:.0f}",
                        f"Test case: {result.test_case.name}",
                    ],
                    alternative_layers=[DiagnosisLayer.PLUGIN],
                )

        return None

    def _check_missing_variable(self, context: DiagnosisContext) -> Optional[LayerDiagnosis]:
        """Check for missing input variable errors."""
        for error in context.error_messages:
            error_lower = error.lower()

            # Common patterns for missing variable
            if any(pattern in error_lower for pattern in [
                "variable not found",
                "unknown variable",
                "undefined variable",
                "no such variable",
                "attributeerror",
            ]):
                # Extract variable name if possible
                var_name = self._extract_variable_name(error)

                return LayerDiagnosis(
                    layer=DiagnosisLayer.VARIABLE_SCHEMA,
                    confidence=0.9,
                    explanation=f"Missing input variable: {var_name or 'unknown'}",
                    suggested_fix=f"Add {var_name or 'the required variable'} to cosilico-us variable schema",
                    evidence=[error],
                )

        return None

    def _check_missing_parameter(self, context: DiagnosisContext) -> Optional[LayerDiagnosis]:
        """Check for missing parameter errors."""
        for error in context.error_messages:
            error_lower = error.lower()

            if any(pattern in error_lower for pattern in [
                "parameter not found",
                "missing parameter",
                "keyerror",
                "no parameter",
            ]):
                param_name = self._extract_param_name(error)

                return LayerDiagnosis(
                    layer=DiagnosisLayer.PARAMETERS,
                    confidence=0.9,
                    explanation=f"Missing parameter: {param_name or 'unknown'}",
                    suggested_fix=f"Add {param_name or 'the required parameter'} to cosilico-data-sources",
                    evidence=[error],
                )

        return None

    def _check_dsl_limitation(self, context: DiagnosisContext) -> Optional[LayerDiagnosis]:
        """Check if the failure is due to DSL limitations."""
        # Check error messages for DSL-related issues
        for error in context.error_messages:
            error_lower = error.lower()

            if any(pattern in error_lower for pattern in [
                "syntax error",
                "parse error",
                "unsupported operation",
                "cannot express",
            ]):
                return LayerDiagnosis(
                    layer=DiagnosisLayer.DSL_CORE,
                    confidence=0.8,
                    explanation="DSL syntax or capability limitation",
                    suggested_fix="Extend cosilico-engine DSL to support this pattern",
                    evidence=[error],
                )

        # Check if variable name suggests a known limitation
        var_lower = context.variable.lower()
        for limitation in self.DSL_LIMITATIONS:
            if limitation in var_lower:
                return LayerDiagnosis(
                    layer=DiagnosisLayer.DSL_CORE,
                    confidence=0.6,
                    explanation=f"Variable involves known DSL limitation: {limitation}",
                    suggested_fix=f"DSL may need extension to handle {limitation}",
                    evidence=[f"Variable name contains '{limitation}'"],
                    alternative_layers=[DiagnosisLayer.PLUGIN],
                )

        return None

    def _check_suspicious_test(self, context: DiagnosisContext) -> Optional[LayerDiagnosis]:
        """Check if the test case itself seems suspicious."""
        expected = context.test_case_expected

        for value in expected.values():
            if not isinstance(value, (int, float)):
                continue

            for suspicious_val, reason in self.SUSPICIOUS_TEST_VALUES:
                if isinstance(suspicious_val, int) and value == suspicious_val:
                    return LayerDiagnosis(
                        layer=DiagnosisLayer.TEST_CASE,
                        confidence=0.6,
                        explanation=f"Test case has suspicious expected value: {value}",
                        suggested_fix="Verify test case expected values against authoritative source",
                        evidence=[reason],
                        alternative_layers=[DiagnosisLayer.PLUGIN],
                    )
                elif isinstance(suspicious_val, float):
                    if value > suspicious_val * 0.9 and value < suspicious_val * 1.1:
                        return LayerDiagnosis(
                            layer=DiagnosisLayer.TEST_CASE,
                            confidence=0.5,
                            explanation=f"Test case value {value} is suspicious",
                            suggested_fix="Verify test case expected values",
                            evidence=[reason],
                            alternative_layers=[DiagnosisLayer.PLUGIN],
                        )

        # Check for inconsistent inputs/outputs
        inputs = context.test_case_inputs
        if inputs.get("employment_income", 0) == 0 and any(v > 0 for v in expected.values() if isinstance(v, (int, float))):
            return LayerDiagnosis(
                layer=DiagnosisLayer.TEST_CASE,
                confidence=0.7,
                explanation="Test expects positive output with zero income",
                suggested_fix="Verify test case inputs match expected outputs",
                evidence=["Zero income but positive expected credit/benefit"],
                alternative_layers=[DiagnosisLayer.PLUGIN],
            )

        return None

    def _plugin_diagnosis(self, context: DiagnosisContext) -> LayerDiagnosis:
        """Default diagnosis: plugin needs improvement."""
        # Try to identify specific plugin issue
        result = context.validation_result

        if result.match_rate < 0.5:
            return LayerDiagnosis(
                layer=DiagnosisLayer.PLUGIN,
                confidence=0.8,
                explanation="Low match rate suggests formula logic error",
                suggested_fix="Review formula generation instructions. Check for missed edge cases.",
                evidence=[
                    f"Match rate: {result.match_rate:.1%}",
                    f"Status: {result.status.value}",
                ],
            )

        if result.match_rate < 0.9:
            return LayerDiagnosis(
                layer=DiagnosisLayer.PLUGIN,
                confidence=0.7,
                explanation="High but imperfect match rate suggests edge case handling",
                suggested_fix="Add specific guidance for edge cases (zero income, phase-out boundaries, etc.)",
                evidence=[
                    f"Match rate: {result.match_rate:.1%}",
                    f"Failed cases: {len(result.issues)}",
                ],
            )

        return LayerDiagnosis(
            layer=DiagnosisLayer.PLUGIN,
            confidence=0.5,
            explanation="Near-perfect match rate with some failures",
            suggested_fix="Investigate specific failing cases for patterns",
            evidence=[f"Match rate: {result.match_rate:.1%}"],
            alternative_layers=[DiagnosisLayer.TEST_CASE, DiagnosisLayer.VALIDATOR],
        )

    def _extract_variable_name(self, error: str) -> Optional[str]:
        """Try to extract variable name from error message."""
        # Common patterns: "Variable 'foo' not found", "unknown variable: foo"
        import re
        patterns = [
            r"variable ['\"]?(\w+)['\"]?",
            r"unknown.*['\"](\w+)['\"]",
            r"undefined.*['\"](\w+)['\"]",
        ]
        for pattern in patterns:
            match = re.search(pattern, error, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    def _extract_param_name(self, error: str) -> Optional[str]:
        """Try to extract parameter name from error message."""
        import re
        patterns = [
            r"parameter ['\"]?(\w+)['\"]?",
            r"keyerror.*['\"](\w+)['\"]",
        ]
        for pattern in patterns:
            match = re.search(pattern, error, re.IGNORECASE)
            if match:
                return match.group(1)
        return None


def diagnose_encoding_failure(
    variable: str,
    validation_result: EncodingValidationResult,
    test_case_inputs: dict[str, Any],
    test_case_expected: dict[str, Any],
    error_messages: Optional[list[str]] = None,
) -> LayerDiagnosis:
    """Convenience function to diagnose an encoding failure.

    Args:
        variable: Variable that failed validation
        validation_result: Result from encoding validation
        test_case_inputs: Inputs used in the failing test
        test_case_expected: Expected outputs from the failing test
        error_messages: Any error messages from the validation

    Returns:
        LayerDiagnosis identifying the likely root cause
    """
    # Extract validator outputs
    validator_outputs = {}
    for result in validation_result.consensus_results:
        for name, vr in result.validator_results.items():
            if vr.calculated_value is not None:
                validator_outputs[name] = vr.calculated_value

    context = DiagnosisContext(
        variable=variable,
        validation_result=validation_result,
        test_case_inputs=test_case_inputs,
        test_case_expected=test_case_expected,
        error_messages=error_messages or [],
        validator_outputs=validator_outputs,
    )

    diagnosis = FailureDiagnosis()
    return diagnosis.diagnose(context)
