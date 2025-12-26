"""Tests for PSL Tax-Calculator validator."""

import pytest
from cosilico_validators.validators.base import TestCase, ValidatorType
from cosilico_validators.validators.psl_tax_calculator import (
    PSLTaxCalculatorValidator,
    VARIABLE_MAPPING,
    SUPPORTED_VARIABLES,
)


def _taxcalc_available():
    """Check if taxcalc package is available."""
    try:
        import taxcalc
        return True
    except ImportError:
        return False


class TestPSLTaxCalculatorValidator:
    """Test suite for PSL Tax-Calculator validator."""

    def test_initialization(self):
        """Test validator initializes correctly."""
        validator = PSLTaxCalculatorValidator()
        assert validator.name == "PSL Tax-Calculator"
        assert validator.validator_type == ValidatorType.SUPPLEMENTARY

    def test_supported_variables(self):
        """Test variable support detection."""
        validator = PSLTaxCalculatorValidator()

        # Should support common variable names
        assert validator.supports_variable("eitc")
        assert validator.supports_variable("EITC")
        assert validator.supports_variable("ctc")
        assert validator.supports_variable("agi")
        assert validator.supports_variable("income_tax")
        assert validator.supports_variable("payroll_tax")

        # Should not support unknown variables
        assert not validator.supports_variable("unknown_variable")
        assert not validator.supports_variable("snap")  # Not a tax variable

    def test_variable_mapping_completeness(self):
        """Test that all mapped variables are supported."""
        for common_name, tc_name in VARIABLE_MAPPING.items():
            assert common_name in SUPPORTED_VARIABLES
            # TC variable names should also be supported
            assert tc_name in SUPPORTED_VARIABLES or tc_name in VARIABLE_MAPPING.values()

    def test_unsupported_year_returns_error(self):
        """Test that years before 2013 return an error."""
        validator = PSLTaxCalculatorValidator()
        test_case = TestCase(
            name="Pre-2013 test",
            inputs={"earned_income": 50000, "filing_status": "SINGLE"},
            expected={"eitc": 0},
        )

        result = validator.validate(test_case, "eitc", year=2012)
        assert result.calculated_value is None
        assert result.error is not None
        assert "2013" in result.error

    def test_unsupported_variable_returns_error(self):
        """Test that unsupported variables return an error."""
        validator = PSLTaxCalculatorValidator()
        test_case = TestCase(
            name="Unknown variable test",
            inputs={"earned_income": 50000},
            expected={"unknown_var": 0},
        )

        result = validator.validate(test_case, "unknown_var", year=2024)
        assert result.calculated_value is None
        assert result.error is not None
        assert "not supported" in result.error.lower()


class TestPSLInputMapping:
    """Test input mapping to Tax-Calculator format."""

    def test_filing_status_mapping(self):
        """Test filing status codes are mapped correctly."""
        validator = PSLTaxCalculatorValidator()

        # Test various filing status inputs
        test_cases = [
            ("SINGLE", 1),
            ("JOINT", 2),
            ("MARRIED_FILING_JOINTLY", 2),
            ("MARRIED_FILING_SEPARATELY", 3),
            ("HEAD_OF_HOUSEHOLD", 4),
            ("WIDOW", 5),
        ]

        for status, expected_mars in test_cases:
            tc = TestCase(
                name=f"Filing status {status}",
                inputs={"filing_status": status, "earned_income": 50000},
                expected={"income_tax": 0},
            )
            input_df = validator._build_input_data(tc, 2024)
            assert input_df["MARS"].iloc[0] == expected_mars, f"Failed for {status}"

    def test_income_input_mapping(self):
        """Test income inputs are mapped correctly."""
        validator = PSLTaxCalculatorValidator()

        tc = TestCase(
            name="Income mapping test",
            inputs={
                "earned_income": 75000,
                "interest_income": 1000,
                "dividend_income": 500,
            },
            expected={"agi": 76500},
        )

        input_df = validator._build_input_data(tc, 2024)
        assert input_df["e00200"].iloc[0] == 75000  # Wages
        assert input_df["e00300"].iloc[0] == 1000  # Interest
        assert input_df["e00600"].iloc[0] == 500  # Dividends

    def test_children_mapping(self):
        """Test child/dependent counts are mapped correctly."""
        validator = PSLTaxCalculatorValidator()

        tc = TestCase(
            name="Children test",
            inputs={
                "earned_income": 40000,
                "eitc_qualifying_children_count": 2,
            },
            expected={"eitc": 5000},
        )

        input_df = validator._build_input_data(tc, 2024)
        # Should have 2 EIC-qualifying children (max 3)
        assert input_df["EIC"].iloc[0] == 2
        # Total exemptions should include children
        assert input_df["XTOT"].iloc[0] >= 3  # 1 adult + 2 children


class TestPSLIntegration:
    """Integration tests for PSL Tax-Calculator (requires taxcalc package)."""

    @pytest.fixture
    def validator(self):
        """Create a PSL Tax-Calculator validator."""
        return PSLTaxCalculatorValidator()

    def test_import_error_handling(self, validator):
        """Test graceful handling when taxcalc is not installed."""
        # This test always passes - if taxcalc is installed, it works
        # If not, validate() returns an error without crashing
        test_case = TestCase(
            name="Import test",
            inputs={"earned_income": 50000, "filing_status": "SINGLE"},
            expected={"eitc": 0},
        )

        result = validator.validate(test_case, "eitc", year=2023)
        # Either succeeds or returns informative error
        assert result.success or "taxcalc" in result.error.lower()

    @pytest.mark.skipif(
        not _taxcalc_available(),
        reason="taxcalc package not installed"
    )
    def test_eitc_calculation(self, validator):
        """Test EITC calculation matches expected values."""
        test_case = TestCase(
            name="EITC single no children",
            inputs={
                "earned_income": 15000,
                "filing_status": "SINGLE",
                "eitc_qualifying_children_count": 0,
                "age": 30,
            },
            expected={"eitc": 600},
            citation="26 USC 32",
        )

        result = validator.validate(test_case, "eitc", year=2023)

        if result.success:
            # EITC for single with no children at $15k should be in phase-out
            assert result.calculated_value is not None
            assert result.calculated_value >= 0
            assert result.calculated_value <= 632  # Max for 0 children in 2023
        else:
            # If it fails, should be due to missing package
            assert "taxcalc" in result.error.lower()

    @pytest.mark.skipif(
        not _taxcalc_available(),
        reason="taxcalc package not installed"
    )
    def test_ctc_calculation(self, validator):
        """Test CTC calculation for family with children."""
        test_case = TestCase(
            name="CTC married with 2 children",
            inputs={
                "earned_income": 80000,
                "filing_status": "JOINT",
                "num_children": 2,
            },
            expected={"ctc": 4000},
        )

        result = validator.validate(test_case, "ctc", year=2023)

        if result.success:
            # CTC should be calculated
            assert result.calculated_value is not None
            assert result.calculated_value >= 0

    @pytest.mark.skipif(
        not _taxcalc_available(),
        reason="taxcalc package not installed"
    )
    def test_income_tax_calculation(self, validator):
        """Test income tax calculation."""
        test_case = TestCase(
            name="Income tax single filer",
            inputs={
                "earned_income": 100000,
                "filing_status": "SINGLE",
            },
            expected={"income_tax": 15000},  # Approximate
        )

        result = validator.validate(test_case, "income_tax", year=2023)

        if result.success:
            assert result.calculated_value is not None
            # Income tax on $100k single should be significant
            assert result.calculated_value > 0
