"""Tests for base validator types."""

from cosilico_validators import TestCase, ValidatorResult, ValidatorType


class TestTestCase:
    def test_basic_creation(self):
        tc = TestCase(
            name="Simple test",
            inputs={"income": 50000},
            expected={"tax": 5000},
        )
        assert tc.name == "Simple test"
        assert tc.inputs == {"income": 50000}
        assert tc.expected == {"tax": 5000}
        assert tc.citation is None

    def test_with_citation(self):
        tc = TestCase(
            name="EITC test",
            inputs={"earned_income": 15000},
            expected={"eitc": 600},
            citation="26 USC § 32(a)(1)",
            notes="Phase-in region",
        )
        assert tc.citation == "26 USC § 32(a)(1)"
        assert tc.notes == "Phase-in region"


class TestValidatorResult:
    def test_successful_result(self):
        result = ValidatorResult(
            validator_name="TestValidator",
            validator_type=ValidatorType.REFERENCE,
            calculated_value=1234.56,
        )
        assert result.success
        assert result.calculated_value == 1234.56
        assert result.error is None

    def test_failed_result(self):
        result = ValidatorResult(
            validator_name="TestValidator",
            validator_type=ValidatorType.REFERENCE,
            calculated_value=None,
            error="Connection timeout",
        )
        assert not result.success
        assert result.calculated_value is None
        assert result.error == "Connection timeout"

    def test_with_metadata(self):
        result = ValidatorResult(
            validator_name="TAXSIM",
            validator_type=ValidatorType.REFERENCE,
            calculated_value=500.0,
            metadata={"year": 2024, "inputs": {"pwages": 15000}},
        )
        assert result.metadata["year"] == 2024
        assert result.metadata["inputs"]["pwages"] == 15000


class TestValidatorType:
    def test_primary_type(self):
        assert ValidatorType.PRIMARY.value == "primary"

    def test_reference_type(self):
        assert ValidatorType.REFERENCE.value == "reference"

    def test_supplementary_type(self):
        assert ValidatorType.SUPPLEMENTARY.value == "supplementary"
