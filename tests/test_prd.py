"""Tests for Atlanta Fed Policy Rules Database validator."""

import pytest
from cosilico_validators.validators.base import TestCase, ValidatorType
from cosilico_validators.validators.atlanta_fed_prd import (
    AtlantaFedPRDValidator,
    VARIABLE_MAPPING,
    SUPPORTED_VARIABLES,
)


class TestAtlantaFedPRDValidator:
    """Test suite for Atlanta Fed PRD validator."""

    def test_initialization(self):
        """Test validator initializes correctly."""
        validator = AtlantaFedPRDValidator()
        assert validator.name == "Atlanta Fed PRD"
        assert validator.validator_type == ValidatorType.SUPPLEMENTARY
        assert validator.cache_dir.exists()

    def test_initialization_with_custom_cache(self, tmp_path):
        """Test validator with custom cache directory."""
        cache_dir = tmp_path / "prd-cache"
        validator = AtlantaFedPRDValidator(cache_dir=cache_dir)
        assert validator.cache_dir == cache_dir
        assert cache_dir.exists()

    def test_supported_variables(self):
        """Test variable support detection."""
        validator = AtlantaFedPRDValidator()

        # Should support SNAP variables
        assert validator.supports_variable("snap")
        assert validator.supports_variable("snap_benefits")
        assert validator.supports_variable("snap_income_limit")
        assert validator.supports_variable("snap_net_income_limit")

        # Should support TANF variables
        assert validator.supports_variable("tanf")
        assert validator.supports_variable("tanf_max_benefit")

        # Should support tax credit variables
        assert validator.supports_variable("eitc")
        assert validator.supports_variable("ctc")
        assert validator.supports_variable("eitc_max_credit")
        assert validator.supports_variable("eitc_phase_in_rate")

        # Should support Medicaid/CHIP
        assert validator.supports_variable("medicaid")
        assert validator.supports_variable("chip")

        # Should not support variables PRD doesn't cover
        assert not validator.supports_variable("income_tax")
        assert not validator.supports_variable("capital_gains_tax")

    def test_variable_mapping_completeness(self):
        """Test that all mapped variables are in supported set."""
        for common_name in VARIABLE_MAPPING.keys():
            assert common_name in SUPPORTED_VARIABLES

    def test_unsupported_variable_returns_error(self):
        """Test that unsupported variables return an error."""
        validator = AtlantaFedPRDValidator()
        test_case = TestCase(
            name="Unknown variable test",
            inputs={"income": 50000},
            expected={"income_tax": 0},
        )

        result = validator.validate(test_case, "income_tax", year=2024)
        assert result.calculated_value is None
        assert result.error is not None
        assert "not supported" in result.error.lower()


class TestPRDFederalPovertyLevel:
    """Test Federal Poverty Level calculations."""

    @pytest.fixture
    def validator(self):
        return AtlantaFedPRDValidator()

    def test_fpl_single_person_2024(self, validator):
        """Test FPL for single person in 2024."""
        fpl = validator._load_federal_poverty_level(2024, household_size=1)
        # 2024 FPL for 1 person is $15,060
        assert fpl == 15060

    def test_fpl_family_of_four_2024(self, validator):
        """Test FPL for family of 4 in 2024."""
        fpl = validator._load_federal_poverty_level(2024, household_size=4)
        # Base + 3 * increment = 15060 + 3 * 5380 = 31,200
        assert fpl == 31200

    def test_fpl_scales_with_household_size(self, validator):
        """Test FPL increases with household size."""
        fpl_1 = validator._load_federal_poverty_level(2024, 1)
        fpl_2 = validator._load_federal_poverty_level(2024, 2)
        fpl_4 = validator._load_federal_poverty_level(2024, 4)

        assert fpl_2 > fpl_1
        assert fpl_4 > fpl_2
        # Each additional person adds the increment
        assert fpl_2 - fpl_1 == fpl_4 - validator._load_federal_poverty_level(2024, 3)


class TestPRDSNAPCalculations:
    """Test SNAP benefit calculations."""

    @pytest.fixture
    def validator(self):
        return AtlantaFedPRDValidator()

    def test_snap_benefit_zero_income(self, validator):
        """Test SNAP benefit for zero income household."""
        test_case = TestCase(
            name="SNAP zero income",
            inputs={
                "gross_income": 0,
                "earned_income": 0,
                "household_size": 1,
            },
            expected={"snap": 291},  # 2024 max for 1 person
        )

        result = validator.validate(test_case, "snap", year=2024)
        assert result.success
        # Should receive maximum benefit
        assert result.calculated_value == 291

    def test_snap_benefit_above_income_limit(self, validator):
        """Test SNAP ineligibility above 130% FPL."""
        # For 1 person, 130% FPL = $19,578
        test_case = TestCase(
            name="SNAP over income limit",
            inputs={
                "gross_income": 25000,  # Well above 130% FPL
                "earned_income": 25000,
                "household_size": 1,
            },
            expected={"snap": 0},
        )

        result = validator.validate(test_case, "snap", year=2024)
        assert result.success
        assert result.calculated_value == 0

    def test_snap_benefit_partial(self, validator):
        """Test SNAP benefit calculation with income."""
        test_case = TestCase(
            name="SNAP partial benefit",
            inputs={
                "gross_income": 1000,
                "earned_income": 1000,
                "household_size": 3,
            },
            expected={"snap": 500},  # Approximate
        )

        result = validator.validate(test_case, "snap", year=2024)
        assert result.success
        # Should receive partial benefit (less than max, more than 0)
        max_benefit = 766  # 2024 max for 3 persons
        assert 0 < result.calculated_value < max_benefit

    def test_snap_income_limit_calculation(self, validator):
        """Test SNAP gross income limit (130% FPL)."""
        test_case = TestCase(
            name="SNAP income limit",
            inputs={"household_size": 4},
            expected={"snap_income_limit": 40560},  # 130% of FPL for 4
        )

        result = validator.validate(test_case, "snap_income_limit", year=2024)
        assert result.success
        # 130% of FPL for 4 = 1.30 * 31200 = 40,560
        assert result.calculated_value == pytest.approx(40560, rel=0.01)

    def test_snap_net_income_limit_calculation(self, validator):
        """Test SNAP net income limit (100% FPL)."""
        test_case = TestCase(
            name="SNAP net income limit",
            inputs={"household_size": 4},
            expected={"snap_net_income_limit": 31200},  # 100% of FPL for 4
        )

        result = validator.validate(test_case, "snap_net_income_limit", year=2024)
        assert result.success
        assert result.calculated_value == 31200


class TestPRDEITCCalculations:
    """Test EITC calculations using PRD parameters."""

    @pytest.fixture
    def validator(self):
        return AtlantaFedPRDValidator()

    def test_eitc_zero_income(self, validator):
        """Test EITC is zero with no income."""
        test_case = TestCase(
            name="EITC no income",
            inputs={
                "earned_income": 0,
                "filing_status": "SINGLE",
                "num_children": 0,
            },
            expected={"eitc": 0},
        )

        result = validator.validate(test_case, "eitc", year=2024)
        assert result.success
        assert result.calculated_value == 0

    def test_eitc_phase_in(self, validator):
        """Test EITC in phase-in region."""
        test_case = TestCase(
            name="EITC phase-in",
            inputs={
                "earned_income": 5000,
                "filing_status": "SINGLE",
                "num_children": 0,
            },
            expected={"eitc": 382.5},  # 5000 * 0.0765
        )

        result = validator.validate(test_case, "eitc", year=2024)
        assert result.success
        # Should be in phase-in: 5000 * 0.0765 = 382.50
        assert result.calculated_value == pytest.approx(382.5, rel=0.01)

    def test_eitc_maximum_credit(self, validator):
        """Test EITC at maximum (plateau region)."""
        test_case = TestCase(
            name="EITC max credit",
            inputs={
                "earned_income": 10000,  # In plateau for 0 children
                "filing_status": "SINGLE",
                "num_children": 0,
            },
            expected={"eitc": 632},
        )

        result = validator.validate(test_case, "eitc", year=2024)
        assert result.success
        # Max credit for 0 children in 2024 is $632
        assert result.calculated_value == 632

    def test_eitc_phase_out(self, validator):
        """Test EITC in phase-out region."""
        test_case = TestCase(
            name="EITC phase-out",
            inputs={
                "earned_income": 15000,
                "filing_status": "SINGLE",
                "num_children": 0,
            },
            expected={"eitc": 274},  # Approximate
        )

        result = validator.validate(test_case, "eitc", year=2024)
        assert result.success
        # Should be reduced but positive
        assert 0 < result.calculated_value < 632

    def test_eitc_with_children(self, validator):
        """Test EITC with qualifying children."""
        test_case = TestCase(
            name="EITC with children",
            inputs={
                "earned_income": 15000,
                "filing_status": "SINGLE",
                "num_children": 2,
            },
            expected={"eitc": 6000},
        )

        result = validator.validate(test_case, "eitc", year=2024)
        assert result.success
        # With 2 children, should get higher credit
        # Phase-in: 15000 * 0.40 = 6000, which is at/near max (6960)
        assert result.calculated_value > 5000

    def test_eitc_joint_filers(self, validator):
        """Test EITC for married filing jointly."""
        test_case = TestCase(
            name="EITC joint filers",
            inputs={
                "earned_income": 25000,
                "filing_status": "JOINT",
                "num_children": 1,
            },
            expected={"eitc": 4000},  # Approximate
        )

        result = validator.validate(test_case, "eitc", year=2024)
        assert result.success
        # Joint filers have higher phase-out thresholds
        assert result.calculated_value > 0

    def test_eitc_max_credit_lookup(self, validator):
        """Test EITC max credit parameter lookup."""
        # 0 children
        test_case_0 = TestCase(
            name="EITC max 0 children",
            inputs={"num_children": 0},
            expected={"eitc_max_credit": 632},
        )
        result_0 = validator.validate(test_case_0, "eitc_max_credit", year=2024)
        assert result_0.calculated_value == 632

        # 2 children
        test_case_2 = TestCase(
            name="EITC max 2 children",
            inputs={"num_children": 2},
            expected={"eitc_max_credit": 6960},
        )
        result_2 = validator.validate(test_case_2, "eitc_max_credit", year=2024)
        assert result_2.calculated_value == 6960

        # 3+ children (max)
        test_case_3 = TestCase(
            name="EITC max 3+ children",
            inputs={"num_children": 5},
            expected={"eitc_max_credit": 7830},
        )
        result_3 = validator.validate(test_case_3, "eitc_max_credit", year=2024)
        assert result_3.calculated_value == 7830

    def test_eitc_phase_in_rate(self, validator):
        """Test EITC phase-in rate lookup."""
        test_case = TestCase(
            name="EITC phase-in rate 1 child",
            inputs={"num_children": 1},
            expected={"eitc_phase_in_rate": 0.34},
        )

        result = validator.validate(test_case, "eitc_phase_in_rate", year=2024)
        assert result.calculated_value == 0.34

    def test_eitc_phase_out_rate(self, validator):
        """Test EITC phase-out rate lookup."""
        test_case = TestCase(
            name="EITC phase-out rate 2 children",
            inputs={"num_children": 2},
            expected={"eitc_phase_out_rate": 0.2106},
        )

        result = validator.validate(test_case, "eitc_phase_out_rate", year=2024)
        assert result.calculated_value == 0.2106


class TestPRDCTCCalculations:
    """Test CTC calculations using PRD parameters."""

    @pytest.fixture
    def validator(self):
        return AtlantaFedPRDValidator()

    def test_ctc_basic_calculation(self, validator):
        """Test basic CTC calculation."""
        test_case = TestCase(
            name="CTC basic",
            inputs={
                "earned_income": 50000,
                "num_children": 2,
            },
            expected={"ctc": 4000},
        )

        result = validator.validate(test_case, "ctc", year=2024)
        assert result.success
        # 2 children * $2000 = $4000
        assert result.calculated_value == 4000

    def test_ctc_max_credit_per_child(self, validator):
        """Test CTC max credit lookup."""
        test_case = TestCase(
            name="CTC max credit",
            inputs={"num_children": 3},
            expected={"ctc_max_credit": 6000},
        )

        result = validator.validate(test_case, "ctc_max_credit", year=2024)
        assert result.success
        # 3 * $2000 = $6000
        assert result.calculated_value == 6000


class TestPRDStateVariation:
    """Test state-specific variations in PRD data."""

    @pytest.fixture
    def validator(self):
        return AtlantaFedPRDValidator()

    def test_snap_with_state(self, validator):
        """Test SNAP calculation includes state in metadata."""
        test_case = TestCase(
            name="SNAP California",
            inputs={
                "gross_income": 1000,
                "earned_income": 1000,
                "household_size": 2,
                "state": "CA",
            },
            expected={"snap": 400},
        )

        result = validator.validate(test_case, "snap", year=2024)
        assert result.success
        assert result.metadata.get("state") == "CA"


class TestPRDYearVariation:
    """Test year-over-year parameter changes."""

    @pytest.fixture
    def validator(self):
        return AtlantaFedPRDValidator()

    def test_eitc_parameters_differ_by_year(self, validator):
        """Test that EITC parameters change between years."""
        test_case = TestCase(
            name="EITC max credit comparison",
            inputs={"num_children": 1},
            expected={"eitc_max_credit": 4000},
        )

        result_2023 = validator.validate(test_case, "eitc_max_credit", year=2023)
        result_2024 = validator.validate(test_case, "eitc_max_credit", year=2024)

        # 2024 should have higher max credit due to inflation adjustments
        assert result_2024.calculated_value > result_2023.calculated_value

    def test_snap_max_benefits_differ_by_year(self, validator):
        """Test that SNAP max benefits change between years."""
        params_2023 = validator._get_snap_parameters(2023)
        params_2024 = validator._get_snap_parameters(2024)

        # 2024 should have higher max benefits
        assert params_2024["max_benefits"][1] > params_2023["max_benefits"][1]


class TestPRDMetadata:
    """Test metadata in validation results."""

    @pytest.fixture
    def validator(self):
        return AtlantaFedPRDValidator()

    def test_result_includes_source(self, validator):
        """Test that results include source information."""
        test_case = TestCase(
            name="Metadata test",
            inputs={"earned_income": 10000, "num_children": 0},
            expected={"eitc": 600},
        )

        result = validator.validate(test_case, "eitc", year=2024)
        assert result.success
        assert "source" in result.metadata
        assert "Atlanta Fed" in result.metadata["source"] or "Policy Rules Database" in result.metadata["source"]

    def test_result_includes_year(self, validator):
        """Test that results include tax year."""
        test_case = TestCase(
            name="Year test",
            inputs={"earned_income": 10000, "num_children": 0},
            expected={"eitc": 600},
        )

        result = validator.validate(test_case, "eitc", year=2024)
        assert result.success
        assert result.metadata.get("year") == 2024
