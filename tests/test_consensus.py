"""Tests for consensus engine."""

import pytest

from cosilico_validators import (
    BaseValidator,
    ConsensusEngine,
    ConsensusLevel,
    TestCase,
    ValidatorResult,
    ValidatorType,
)


class MockValidator(BaseValidator):
    """Mock validator for testing."""

    def __init__(
        self,
        name: str,
        validator_type: ValidatorType,
        return_value: float | None,
        error: str | None = None,
    ):
        self.name = name
        self.validator_type = validator_type
        self._return_value = return_value
        self._error = error
        self.supported_variables = {"eitc", "ctc", "income_tax"}

    def supports_variable(self, variable: str) -> bool:
        return variable.lower() in self.supported_variables

    def validate(
        self, test_case: TestCase, variable: str, year: int = 2024
    ) -> ValidatorResult:
        return ValidatorResult(
            validator_name=self.name,
            validator_type=self.validator_type,
            calculated_value=self._return_value,
            error=self._error,
        )


@pytest.fixture
def simple_test_case():
    return TestCase(
        name="EITC basic test",
        inputs={"earned_income": 15000, "filing_status": "SINGLE"},
        expected={"eitc": 600},
        citation="26 USC § 32",
    )


class TestConsensusEngine:
    def test_full_agreement(self, simple_test_case):
        """All validators agree within tolerance."""
        validators = [
            MockValidator("V1", ValidatorType.PRIMARY, 600),
            MockValidator("V2", ValidatorType.REFERENCE, 605),
            MockValidator("V3", ValidatorType.REFERENCE, 598),
        ]
        engine = ConsensusEngine(validators, tolerance=15.0)
        result = engine.validate(simple_test_case, "eitc", 2024)

        assert result.consensus_level == ConsensusLevel.FULL_AGREEMENT
        assert result.consensus_value is not None
        assert abs(result.consensus_value - 601) < 1  # mean of 600, 605, 598
        assert result.reward_signal > 0.5  # High reward for full agreement

    def test_primary_confirmed(self, simple_test_case):
        """Primary validator + majority agree."""
        validators = [
            MockValidator("Primary", ValidatorType.PRIMARY, 600),
            MockValidator("V2", ValidatorType.REFERENCE, 605),
            MockValidator("V3", ValidatorType.REFERENCE, 800),  # Outlier
        ]
        engine = ConsensusEngine(validators, tolerance=15.0)
        result = engine.validate(simple_test_case, "eitc", 2024)

        assert result.consensus_level == ConsensusLevel.PRIMARY_CONFIRMED
        assert result.consensus_value == 600
        assert result.reward_signal > 0.4

    def test_disagreement(self, simple_test_case):
        """No consensus when validators wildly disagree."""
        validators = [
            MockValidator("V1", ValidatorType.REFERENCE, 100),
            MockValidator("V2", ValidatorType.REFERENCE, 500),
            MockValidator("V3", ValidatorType.REFERENCE, 900),
        ]
        engine = ConsensusEngine(validators, tolerance=15.0)
        result = engine.validate(simple_test_case, "eitc", 2024)

        assert result.consensus_level == ConsensusLevel.DISAGREEMENT
        assert result.reward_signal < 0  # Negative reward for disagreement

    def test_potential_upstream_bug(self, simple_test_case):
        """Claude confident but validators disagree with expected."""
        validators = [
            MockValidator("V1", ValidatorType.REFERENCE, 800),  # Different from expected 600
            MockValidator("V2", ValidatorType.REFERENCE, 850),
        ]
        engine = ConsensusEngine(validators, tolerance=15.0)
        result = engine.validate(simple_test_case, "eitc", 2024, claude_confidence=0.95)

        assert result.consensus_level == ConsensusLevel.POTENTIAL_UPSTREAM_BUG
        assert len(result.potential_bugs) > 0
        assert result.potential_bugs[0]["expected"] == 600
        assert result.potential_bugs[0]["actual"] in [800, 850]

    def test_no_validators_succeed(self, simple_test_case):
        """All validators fail."""
        validators = [
            MockValidator("V1", ValidatorType.REFERENCE, None, error="Failed"),
            MockValidator("V2", ValidatorType.REFERENCE, None, error="Also failed"),
        ]
        engine = ConsensusEngine(validators, tolerance=15.0)
        result = engine.validate(simple_test_case, "eitc", 2024)

        assert result.consensus_level == ConsensusLevel.DISAGREEMENT
        assert result.consensus_value is None
        assert result.confidence == 0.0

    def test_reward_signal_bounds(self, simple_test_case):
        """Reward signal stays within [-1, 1]."""
        validators = [
            MockValidator("V1", ValidatorType.PRIMARY, 600),
            MockValidator("V2", ValidatorType.REFERENCE, 600),
            MockValidator("V3", ValidatorType.REFERENCE, 600),
        ]
        engine = ConsensusEngine(validators, tolerance=15.0)
        result = engine.validate(simple_test_case, "eitc", 2024)

        assert -1.0 <= result.reward_signal <= 1.0

    def test_confidence_calculation(self, simple_test_case):
        """Confidence reflects success rate and agreement."""
        validators = [
            MockValidator("V1", ValidatorType.PRIMARY, 600),
            MockValidator("V2", ValidatorType.REFERENCE, 600),
            MockValidator("V3", ValidatorType.REFERENCE, None, error="Failed"),
        ]
        engine = ConsensusEngine(validators, tolerance=15.0)
        result = engine.validate(simple_test_case, "eitc", 2024)

        assert 0.0 <= result.confidence <= 1.0
        # 2/3 success rate + agreement + primary bonus
        assert result.confidence > 0.5

    def test_batch_validate(self, simple_test_case):
        """Batch validation works correctly."""
        validators = [MockValidator("V1", ValidatorType.REFERENCE, 600)]
        engine = ConsensusEngine(validators)

        test_cases = [simple_test_case, simple_test_case]
        results = engine.batch_validate(test_cases, "eitc", 2024)

        assert len(results) == 2
        for r in results:
            assert r.consensus_value is not None


class TestValidationResult:
    def test_matches_expected_within_tolerance(self, simple_test_case):
        """Result matches when within $15 tolerance."""
        validators = [MockValidator("V1", ValidatorType.REFERENCE, 610)]
        engine = ConsensusEngine(validators)
        result = engine.validate(simple_test_case, "eitc", 2024)

        assert result.matches_expected  # 610 vs 600, diff = 10 < 15

    def test_does_not_match_outside_tolerance(self, simple_test_case):
        """Result doesn't match when outside tolerance."""
        validators = [MockValidator("V1", ValidatorType.REFERENCE, 620)]
        engine = ConsensusEngine(validators)
        result = engine.validate(simple_test_case, "eitc", 2024)

        assert not result.matches_expected  # 620 vs 600, diff = 20 > 15

    def test_summary_generation(self, simple_test_case):
        """Summary string is generated correctly."""
        validators = [MockValidator("V1", ValidatorType.REFERENCE, 600)]
        engine = ConsensusEngine(validators)
        result = engine.validate(simple_test_case, "eitc", 2024)

        summary = result.summary()
        assert "EITC basic test" in summary
        assert "$600" in summary
        assert "Reward:" in summary
