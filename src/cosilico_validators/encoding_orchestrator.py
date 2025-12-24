"""Encoding Orchestrator - Ties together the validation-driven encoding system.

This is the main entry point for encoding variables through the system:
1. Select plugin version (Thompson sampling)
2. Generate test cases for the variable
3. Validate against PolicyEngine
4. Diagnose failures (multi-layer)
5. Log results and suggest improvements
6. Create forecasted improvement decisions if needed
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .encoding_validator import validate_encoding, EncodingValidationResult, ValidationStatus
from .plugin_history import get_history_tools, FailureSummary
from .failure_diagnosis import diagnose_encoding_failure, DiagnosisLayer, LayerDiagnosis
from .adaptive_validator import get_adaptive_validator
from .improvement_decisions import create_improvement_decision, get_decision_log


RESULTS_DIR = Path(__file__).parent.parent.parent.parent / "results"


@dataclass
class EncodingSession:
    """A complete encoding session for a variable."""

    variable: str
    statute_ref: str
    plugin_version: str
    test_cases: list[dict]
    validation_result: Optional[EncodingValidationResult] = None
    diagnosis: Optional[LayerDiagnosis] = None
    improvement_decision_id: Optional[str] = None
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat() + "Z"


class EncodingOrchestrator:
    """Orchestrates the encoding → validation → diagnosis → improvement loop."""

    def __init__(
        self,
        plugin_version: str = "v0.1.0",
        results_dir: Optional[Path] = None,
    ):
        """Initialize the orchestrator.

        Args:
            plugin_version: Current plugin version (git commit or tag)
            results_dir: Directory for storing results
        """
        self.plugin_version = plugin_version
        self.results_dir = results_dir or RESULTS_DIR
        self.results_dir.mkdir(parents=True, exist_ok=True)

        self.sessions_file = self.results_dir / "encoding_sessions.jsonl"

        # Get component instances
        self.history = get_history_tools()
        self.adaptive = get_adaptive_validator()
        self.decision_log = get_decision_log()

        # Register plugin version
        self.adaptive.register_plugin(plugin_version)

    def encode_and_validate(
        self,
        variable: str,
        statute_ref: str,
        test_cases: list[dict],
        year: int = 2024,
    ) -> EncodingSession:
        """Run the full encoding → validation → diagnosis cycle.

        Args:
            variable: Variable name to encode (e.g., "adjusted_gross_income")
            statute_ref: Statute reference (e.g., "26 USC § 62(a)")
            test_cases: Test cases with inputs and expected outputs
            year: Tax year for validation

        Returns:
            EncodingSession with full results
        """
        session = EncodingSession(
            variable=variable,
            statute_ref=statute_ref,
            plugin_version=self.plugin_version,
            test_cases=test_cases,
        )

        # Step 1: Validate encoding against PolicyEngine
        print(f"\n{'='*60}")
        print(f"Validating: {variable}")
        print(f"Statute: {statute_ref}")
        print(f"Plugin: {self.plugin_version}")
        print(f"{'='*60}\n")

        session.validation_result = validate_encoding(
            variable=variable,
            test_cases=test_cases,
            year=year,
        )

        print(session.validation_result.summary())

        # Step 2: Record results in adaptive validator
        self.adaptive.record_validation(
            version=self.plugin_version,
            variable=variable,
            match_rate=session.validation_result.match_rate,
            success=session.validation_result.passed,
        )

        # Step 3: If failed, diagnose and suggest improvements
        if not session.validation_result.passed:
            session.diagnosis = self._diagnose_failure(session)
            print(f"\n--- Diagnosis ---")
            print(f"Layer: {session.diagnosis.layer.value}")
            print(f"Confidence: {session.diagnosis.confidence:.0%}")
            print(f"Explanation: {session.diagnosis.explanation}")
            print(f"Suggested Fix: {session.diagnosis.suggested_fix}")

            # Log failure
            self._log_failure(session)

            # Create improvement decision if plugin issue
            if session.diagnosis.layer == DiagnosisLayer.PLUGIN:
                session.improvement_decision_id = self._create_improvement_decision(session)

        # Save session
        self._save_session(session)

        return session

    def _diagnose_failure(self, session: EncodingSession) -> LayerDiagnosis:
        """Diagnose why the encoding failed."""
        # Get error messages from validation result
        error_messages = []
        for issue in session.validation_result.issues:
            if "error" in issue:
                error_messages.append(issue["error"])

        # Get test case details for diagnosis
        test_inputs = session.test_cases[0].get("inputs", {}) if session.test_cases else {}
        test_expected = session.test_cases[0].get("expected", {}) if session.test_cases else {}

        return diagnose_encoding_failure(
            variable=session.variable,
            validation_result=session.validation_result,
            test_case_inputs=test_inputs,
            test_case_expected=test_expected,
            error_messages=error_messages,
        )

    def _log_failure(self, session: EncodingSession) -> None:
        """Log failure to history for future reference."""
        self.history.log_failure(
            variable=session.variable,
            match_rate=session.validation_result.match_rate,
            error_type=session.validation_result.status.value,
            layer=session.diagnosis.layer.value,
            plugin_version=self.plugin_version,
            test_cases_failed=len(session.validation_result.issues),
            test_cases_total=len(session.test_cases),
            root_cause=session.diagnosis.explanation,
            details={
                "statute_ref": session.statute_ref,
                "suggested_fix": session.diagnosis.suggested_fix,
                "evidence": session.diagnosis.evidence,
            },
        )

    def _create_improvement_decision(self, session: EncodingSession) -> str:
        """Create a forecasted improvement decision for plugin changes."""
        # Look up similar past failures to inform forecast
        similar = self.history.get_similar_failures(session.variable)

        # Check calibration to adjust confidence intervals
        calibration = self.history.get_calibration()

        # Estimate improvement based on diagnosis
        base_improvement = self._estimate_improvement(session.diagnosis)

        # Widen CI if we've been overconfident
        ci_width = 0.08  # Base: ±4 percentage points
        if calibration.calibration_error and calibration.calibration_error < -0.1:
            ci_width *= 1.5  # Widen if overconfident

        decision = create_improvement_decision(
            question=f"How should we improve encoding of {session.variable}?",
            context=f"Current match rate: {session.validation_result.match_rate:.1%}. "
                   f"Diagnosis: {session.diagnosis.explanation}",
            options=[
                {
                    "name": "plugin_refinement",
                    "description": session.diagnosis.suggested_fix,
                    "layer": "plugin",
                    "effort": "small",
                    "forecasts": {
                        "match_rate": {
                            "point": base_improvement,
                            "ci": (base_improvement - ci_width, base_improvement + ci_width),
                            "reasoning": f"Based on diagnosis: {session.diagnosis.explanation}. "
                                        f"Similar failures: {len(similar)}",
                        }
                    }
                },
                {
                    "name": "no_change",
                    "description": "Accept current match rate, document edge cases",
                    "layer": "plugin",
                    "effort": "trivial",
                    "forecasts": {
                        "match_rate": {
                            "point": 0.0,
                            "ci": (-0.01, 0.01),
                            "reasoning": "No change expected",
                        }
                    }
                },
            ],
        )

        print(f"\n--- Improvement Decision Created: {decision.id} ---")
        best = decision.best_option()
        if best:
            forecast = best.forecasts.get("match_rate")
            if forecast:
                print(f"Recommended: {best.name}")
                print(f"Expected improvement: +{forecast.point_estimate:.1f}pp "
                      f"(80% CI: [{forecast.confidence_interval[0]:.1f}, {forecast.confidence_interval[1]:.1f}])")

        return decision.id

    def _estimate_improvement(self, diagnosis: LayerDiagnosis) -> float:
        """Estimate expected improvement from fixing the diagnosed issue.

        Returns percentage point improvement estimate.
        """
        # Base estimates by diagnosis layer
        layer_estimates = {
            DiagnosisLayer.PLUGIN: 0.08,  # 8 percentage points
            DiagnosisLayer.TEST_CASE: 0.05,  # Test case fixes usually smaller
            DiagnosisLayer.VALIDATOR: 0.10,  # Upstream bugs can have big impact
            DiagnosisLayer.VARIABLE_SCHEMA: 0.15,  # Missing variables = big gap
            DiagnosisLayer.PARAMETERS: 0.10,  # Missing params = moderate gap
            DiagnosisLayer.DSL_CORE: 0.20,  # DSL limits can block entire features
        }

        # Adjust by diagnosis confidence
        base = layer_estimates.get(diagnosis.layer, 0.05)
        return base * diagnosis.confidence

    def _save_session(self, session: EncodingSession) -> None:
        """Save encoding session to log."""
        data = {
            "variable": session.variable,
            "statute_ref": session.statute_ref,
            "plugin_version": session.plugin_version,
            "timestamp": session.timestamp,
            "match_rate": session.validation_result.match_rate if session.validation_result else None,
            "passed": session.validation_result.passed if session.validation_result else None,
            "status": session.validation_result.status.value if session.validation_result else None,
            "diagnosis_layer": session.diagnosis.layer.value if session.diagnosis else None,
            "improvement_decision_id": session.improvement_decision_id,
        }

        with open(self.sessions_file, "a") as f:
            f.write(json.dumps(data) + "\n")

    def get_progress_summary(self) -> dict[str, Any]:
        """Get summary of encoding progress."""
        adaptive_stats = self.adaptive.get_statistics()
        calibration = self.decision_log.get_calibration_summary()

        # Count sessions by status
        sessions_by_status = {"passed": 0, "failed": 0}
        if self.sessions_file.exists():
            with open(self.sessions_file) as f:
                for line in f:
                    data = json.loads(line)
                    if data.get("passed"):
                        sessions_by_status["passed"] += 1
                    else:
                        sessions_by_status["failed"] += 1

        return {
            "plugin_version": self.plugin_version,
            "sessions": sessions_by_status,
            "validation": adaptive_stats,
            "calibration": calibration,
        }


# Convenience functions

def encode_variable(
    variable: str,
    statute_ref: str,
    test_cases: list[dict],
    plugin_version: str = "v0.1.0",
    year: int = 2024,
) -> EncodingSession:
    """Convenience function to encode and validate a variable.

    Example:
        session = encode_variable(
            variable="adjusted_gross_income",
            statute_ref="26 USC § 62(a)",
            test_cases=[
                {
                    "name": "Simple wages",
                    "inputs": {"employment_income": 50000, "filing_status": "SINGLE"},
                    "expected": {"adjusted_gross_income": 50000},
                },
            ],
        )
    """
    orchestrator = EncodingOrchestrator(plugin_version=plugin_version)
    return orchestrator.encode_and_validate(
        variable=variable,
        statute_ref=statute_ref,
        test_cases=test_cases,
        year=year,
    )


# Standard test cases for common variables

AGI_TEST_CASES = [
    {
        "name": "Simple wages - single",
        "inputs": {"employment_income": 50000, "filing_status": "SINGLE"},
        "expected": {"adjusted_gross_income": 50000},
        "citation": "26 USC § 62(a)",
    },
    {
        "name": "Wages plus self-employment",
        "inputs": {
            "employment_income": 40000,
            "self_employment_income": 10000,
            "filing_status": "SINGLE",
        },
        "expected": {"adjusted_gross_income": 50000},  # Approximate - SE tax deduction
        "citation": "26 USC § 62(a)",
    },
    {
        "name": "Multiple income sources - joint",
        "inputs": {
            "employment_income": 80000,
            "interest_income": 1000,
            "dividend_income": 2000,
            "filing_status": "JOINT",
        },
        "expected": {"adjusted_gross_income": 83000},
        "citation": "26 USC § 62(a)",
    },
    {
        "name": "Zero income",
        "inputs": {"employment_income": 0, "filing_status": "SINGLE"},
        "expected": {"adjusted_gross_income": 0},
        "citation": "26 USC § 62(a)",
    },
]

EARNED_INCOME_TEST_CASES = [
    {
        "name": "Simple wages",
        "inputs": {"employment_income": 30000, "filing_status": "SINGLE"},
        "expected": {"earned_income": 30000},
        "citation": "26 USC § 32(c)(2)(A)",
    },
    {
        "name": "Self-employment income",
        "inputs": {"self_employment_income": 20000, "filing_status": "SINGLE"},
        "expected": {"earned_income": 20000},  # Approximate
        "citation": "26 USC § 32(c)(2)(A)(ii)",
    },
    {
        "name": "Zero earnings",
        "inputs": {"employment_income": 0, "filing_status": "SINGLE"},
        "expected": {"earned_income": 0},
        "citation": "26 USC § 32(c)(2)(A)",
    },
]

EITC_TEST_CASES = [
    {
        "name": "EITC phase-in, no children",
        "inputs": {
            "employment_income": 5000,
            "filing_status": "SINGLE",
            "eitc_qualifying_children_count": 0,
        },
        "expected": {"eitc": 383},  # 5000 × 0.0765
        "citation": "26 USC § 32(a)(1)",
    },
    {
        "name": "EITC maximum, 1 child",
        "inputs": {
            "employment_income": 15000,
            "filing_status": "SINGLE",
            "eitc_qualifying_children_count": 1,
        },
        "expected": {"eitc": None},  # Let PE tell us
        "citation": "26 USC § 32(a)(2)",
    },
    {
        "name": "EITC phase-out, 2 children",
        "inputs": {
            "employment_income": 40000,
            "filing_status": "SINGLE",
            "eitc_qualifying_children_count": 2,
        },
        "expected": {"eitc": None},
        "citation": "26 USC § 32(a)(2)(B)",
    },
    {
        "name": "EITC zero - high income",
        "inputs": {
            "employment_income": 60000,
            "filing_status": "SINGLE",
            "eitc_qualifying_children_count": 1,
        },
        "expected": {"eitc": 0},
        "citation": "26 USC § 32",
    },
]


if __name__ == "__main__":
    # Run a quick test
    print("Testing Encoding Orchestrator\n")

    session = encode_variable(
        variable="adjusted_gross_income",
        statute_ref="26 USC § 62(a)",
        test_cases=AGI_TEST_CASES,
    )

    print(f"\n{'='*60}")
    print("SESSION SUMMARY")
    print(f"{'='*60}")
    print(f"Variable: {session.variable}")
    print(f"Match Rate: {session.validation_result.match_rate:.1%}")
    print(f"Passed: {'YES' if session.validation_result.passed else 'NO'}")
    if session.diagnosis:
        print(f"Diagnosis: {session.diagnosis.layer.value}")
    if session.improvement_decision_id:
        print(f"Improvement Decision: {session.improvement_decision_id}")
