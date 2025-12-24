"""Encoding validation loop - validates new DSL encodings against PE/TAXSIM.

This is the core RL feedback mechanism. Every new encoding must achieve
FULL_AGREEMENT or document upstream bugs.

Usage:
    from cosilico_validators.encoding_validator import validate_encoding

    result = validate_encoding(
        variable="amt",
        test_cases=[...],
        cosilico_func=calculate_amt,
    )

    if result.passed:
        print("Ready to merge!")
    else:
        print(f"Issues: {result.issues}")
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from enum import Enum

from .consensus.engine import ConsensusEngine, ConsensusLevel, ValidationResult
from .validators.base import TestCase
from .validators.policyengine import PolicyEngineValidator


class ValidationStatus(Enum):
    """Overall validation status."""
    PASSED = "passed"  # FULL_AGREEMENT achieved
    UPSTREAM_BUG = "upstream_bug"  # Discrepancy is PE/TAXSIM bug
    ENCODING_ERROR = "encoding_error"  # Our encoding is wrong
    NEEDS_INVESTIGATION = "needs_investigation"  # Unclear


@dataclass
class EncodingValidationResult:
    """Result of validating a new encoding against PE/TAXSIM."""

    variable: str
    status: ValidationStatus
    consensus_results: List[ValidationResult]
    passed: bool
    match_rate: float  # % of test cases with FULL_AGREEMENT
    reward_signal: float  # Aggregate reward for RL training
    issues: List[Dict[str, Any]] = field(default_factory=list)
    upstream_bugs: List[Dict[str, Any]] = field(default_factory=list)

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [
            f"Variable: {self.variable}",
            f"Status: {self.status.value}",
            f"Match Rate: {self.match_rate:.1%}",
            f"Reward Signal: {self.reward_signal:+.2f}",
            f"Passed: {'✅' if self.passed else '❌'}",
        ]
        if self.issues:
            lines.append(f"Issues: {len(self.issues)}")
        if self.upstream_bugs:
            lines.append(f"Upstream Bugs: {len(self.upstream_bugs)}")
        return "\n".join(lines)


def validate_encoding(
    variable: str,
    test_cases: List[Dict[str, Any]],
    cosilico_func: Optional[Callable] = None,
    year: int = 2024,
    tolerance: float = 15.0,
    require_full_agreement: bool = True,
    claude_confidence: float = 0.95,
) -> EncodingValidationResult:
    """
    Validate a new encoding against PolicyEngine (and optionally TAXSIM).

    This is the RL reward function. Every new encoding should pass through here.

    Args:
        variable: Name of the variable being encoded (e.g., "amt", "eitc")
        test_cases: List of test case dicts with "inputs" and "expected" keys
        cosilico_func: Optional callable that computes our value (for comparison)
        year: Tax year to validate
        tolerance: Dollar tolerance for matching ($15 default)
        require_full_agreement: If True, only FULL_AGREEMENT counts as pass
        claude_confidence: Confidence level for upstream bug detection

    Returns:
        EncodingValidationResult with pass/fail status and details
    """
    # Initialize validators
    try:
        pe_validator = PolicyEngineValidator()
        validators = [pe_validator]
    except Exception as e:
        return EncodingValidationResult(
            variable=variable,
            status=ValidationStatus.NEEDS_INVESTIGATION,
            consensus_results=[],
            passed=False,
            match_rate=0.0,
            reward_signal=-1.0,
            issues=[{"error": f"Failed to initialize validators: {e}"}],
        )

    engine = ConsensusEngine(validators, tolerance=tolerance)

    # Convert test cases to TestCase objects
    converted_cases = []
    for tc in test_cases:
        converted_cases.append(TestCase(
            name=tc.get("name", f"test_{len(converted_cases)}"),
            inputs=tc.get("inputs", {}),
            expected=tc.get("expected", {}),
            citation=tc.get("citation", ""),
        ))

    # Run validation
    results = []
    issues = []
    upstream_bugs = []
    total_reward = 0.0

    for tc in converted_cases:
        try:
            result = engine.validate(
                tc, variable, year, claude_confidence=claude_confidence
            )
            results.append(result)
            total_reward += result.reward_signal

            # Check for issues
            if result.consensus_level == ConsensusLevel.DISAGREEMENT:
                issues.append({
                    "test_case": tc.name,
                    "expected": result.expected_value,
                    "consensus": result.consensus_value,
                    "level": result.consensus_level.value,
                })
            elif result.consensus_level == ConsensusLevel.POTENTIAL_UPSTREAM_BUG:
                upstream_bugs.extend(result.potential_bugs)

        except Exception as e:
            issues.append({
                "test_case": tc.name,
                "error": str(e),
            })

    # Calculate metrics
    n_full_agreement = sum(
        1 for r in results
        if r.consensus_level == ConsensusLevel.FULL_AGREEMENT
    )
    match_rate = n_full_agreement / len(results) if results else 0.0
    avg_reward = total_reward / len(results) if results else -1.0

    # Determine status
    if match_rate == 1.0:
        status = ValidationStatus.PASSED
        passed = True
    elif upstream_bugs:
        status = ValidationStatus.UPSTREAM_BUG
        passed = not require_full_agreement  # Pass if we found upstream bugs
    elif issues:
        status = ValidationStatus.ENCODING_ERROR
        passed = False
    else:
        status = ValidationStatus.NEEDS_INVESTIGATION
        passed = False

    return EncodingValidationResult(
        variable=variable,
        status=status,
        consensus_results=results,
        passed=passed,
        match_rate=match_rate,
        reward_signal=avg_reward,
        issues=issues,
        upstream_bugs=upstream_bugs,
    )


def validate_amt(year: int = 2024) -> EncodingValidationResult:
    """Validate AMT encoding against PolicyEngine."""
    test_cases = [
        {
            "name": "AMT single, below exemption",
            "inputs": {
                "employment_income": 50000,
                "filing_status": "SINGLE",
            },
            "expected": {"alternative_minimum_tax": 0},
            "citation": "26 USC § 55(d)(1)(A)",
        },
        {
            "name": "AMT single, above exemption",
            "inputs": {
                "employment_income": 200000,
                "filing_status": "SINGLE",
            },
            "expected": {"alternative_minimum_tax": None},  # Let PE tell us
            "citation": "26 USC § 55",
        },
        {
            "name": "AMT joint, phaseout region",
            "inputs": {
                "employment_income": 1200000,
                "filing_status": "JOINT",
            },
            "expected": {"alternative_minimum_tax": None},
            "citation": "26 USC § 55(d)(2)",
        },
    ]

    return validate_encoding(
        variable="alternative_minimum_tax",
        test_cases=test_cases,
        year=year,
    )


def validate_salt(year: int = 2024) -> EncodingValidationResult:
    """Validate SALT cap encoding against PolicyEngine."""
    test_cases = [
        {
            "name": "SALT below cap",
            "inputs": {
                "state_and_local_sales_or_income_tax": 5000,
                "real_estate_taxes": 3000,
                "filing_status": "SINGLE",
            },
            "expected": {"salt_deduction": 8000},
            "citation": "26 USC § 164(b)(6)",
        },
        {
            "name": "SALT at cap",
            "inputs": {
                "state_and_local_sales_or_income_tax": 8000,
                "real_estate_taxes": 5000,
                "filing_status": "SINGLE",
            },
            "expected": {"salt_deduction": 10000},
            "citation": "26 USC § 164(b)(6)",
        },
        {
            "name": "SALT MFS half cap",
            "inputs": {
                "state_and_local_sales_or_income_tax": 8000,
                "real_estate_taxes": 5000,
                "filing_status": "SEPARATE",
            },
            "expected": {"salt_deduction": 5000},
            "citation": "26 USC § 164(b)(6)(B)",
        },
    ]

    return validate_encoding(
        variable="salt_deduction",
        test_cases=test_cases,
        year=year,
    )


if __name__ == "__main__":
    print("=" * 60)
    print("ENCODING VALIDATION - RL Reward Loop")
    print("=" * 60)

    print("\n--- AMT Validation ---")
    amt_result = validate_amt()
    print(amt_result.summary())

    print("\n--- SALT Validation ---")
    salt_result = validate_salt()
    print(salt_result.summary())

    print("\n" + "=" * 60)
    if amt_result.passed and salt_result.passed:
        print("✅ All encodings validated!")
    else:
        print("❌ Some encodings need work")
        if amt_result.issues:
            print(f"  AMT issues: {len(amt_result.issues)}")
        if salt_result.issues:
            print(f"  SALT issues: {len(salt_result.issues)}")
