"""Tests for Yale Budget Lab validator."""

import pytest
from cosilico_validators.validators.base import TestCase, ValidatorType
from cosilico_validators.validators.yale_budget_lab import (
    YaleBudgetLabValidator,
    VARIABLE_MAPPING,
    SUPPORTED_VARIABLES,
)


class TestYaleBudgetLabValidator:
    """Test suite for Yale Budget Lab validator."""

    def test_initialization(self):
        """Test validator initializes correctly."""
        validator = YaleBudgetLabValidator()
        assert validator.name == "Yale Budget Lab"
        assert validator.validator_type == ValidatorType.SUPPLEMENTARY
        assert validator.cache_dir.exists()

    def test_initialization_with_custom_cache(self, tmp_path):
        """Test validator with custom cache directory."""
        cache_dir = tmp_path / "ybl-cache"
        validator = YaleBudgetLabValidator(cache_dir=cache_dir)
        assert validator.cache_dir == cache_dir
        assert cache_dir.exists()

    def test_supported_variables(self):
        """Test variable support detection."""
        validator = YaleBudgetLabValidator()

        # Should support policy parameters
        assert validator.supports_variable("top_marginal_rate")
        assert validator.supports_variable("corporate_rate")
        assert validator.supports_variable("capital_gains_rate")

        # Should support tariff analysis
        assert validator.supports_variable("effective_tariff_rate")
        assert validator.supports_variable("tariff_revenue")

        # Should support distributional metrics
        assert validator.supports_variable("tax_burden_bottom_quintile")
        assert validator.supports_variable("tax_burden_top_1pct")
        assert validator.supports_variable("effective_tax_rate")

        # Should support tax filing burden
        assert validator.supports_variable("tax_filing_time_hours")
        assert validator.supports_variable("tax_filing_cost")

        # Should not support individual tax variables
        assert not validator.supports_variable("eitc")
        assert not validator.supports_variable("income_tax")

    def test_variable_mapping_completeness(self):
        """Test that all mapped variables are in supported set."""
        for common_name in VARIABLE_MAPPING.keys():
            assert common_name in SUPPORTED_VARIABLES

    def test_unsupported_variable_returns_error(self):
        """Test that unsupported variables return an error."""
        validator = YaleBudgetLabValidator()
        test_case = TestCase(
            name="Unknown variable test",
            inputs={"income": 50000},
            expected={"eitc": 0},
        )

        result = validator.validate(test_case, "eitc", year=2024)
        assert result.calculated_value is None
        assert result.error is not None
        assert "not supported" in result.error.lower()


class TestYBLTaxParameters:
    """Test tax parameter lookups."""

    @pytest.fixture
    def validator(self):
        return YaleBudgetLabValidator()

    def test_top_marginal_rate_tcja(self, validator):
        """Test top marginal rate during TCJA (2018-2025)."""
        test_case = TestCase(
            name="TCJA top rate",
            inputs={},
            expected={"top_marginal_rate": 0.37},
        )

        result = validator.validate(test_case, "top_marginal_rate", year=2024)
        assert result.success
        assert result.calculated_value == 0.37

    def test_top_marginal_rate_post_tcja(self, validator):
        """Test top marginal rate after TCJA sunset (2026+)."""
        test_case = TestCase(
            name="Post-TCJA top rate",
            inputs={},
            expected={"top_marginal_rate": 0.396},
        )

        result = validator.validate(test_case, "top_marginal_rate", year=2026)
        assert result.success
        assert result.calculated_value == 0.396

    def test_corporate_rate(self, validator):
        """Test corporate tax rate."""
        test_case = TestCase(
            name="Corporate rate",
            inputs={},
            expected={"corporate_rate": 0.21},
        )

        result = validator.validate(test_case, "corporate_rate", year=2024)
        assert result.success
        assert result.calculated_value == 0.21

    def test_capital_gains_rate(self, validator):
        """Test capital gains rate."""
        test_case = TestCase(
            name="Capital gains rate",
            inputs={},
            expected={"capital_gains_rate": 0.20},
        )

        result = validator.validate(test_case, "capital_gains_rate", year=2024)
        assert result.success
        assert result.calculated_value == 0.20


class TestYBLTariffData:
    """Test tariff data lookups."""

    @pytest.fixture
    def validator(self):
        return YaleBudgetLabValidator()

    def test_effective_tariff_rate_2025(self, validator):
        """Test elevated tariff rate in 2025."""
        test_case = TestCase(
            name="2025 tariff rate",
            inputs={},
            expected={"effective_tariff_rate": 0.168},
        )

        result = validator.validate(test_case, "effective_tariff_rate", year=2025)
        assert result.success
        # Should reflect elevated 2025 tariff rates
        assert result.calculated_value == pytest.approx(0.168, rel=0.01)

    def test_effective_tariff_rate_pre_2025(self, validator):
        """Test lower tariff rate before 2025."""
        test_case = TestCase(
            name="Pre-2025 tariff rate",
            inputs={},
            expected={"effective_tariff_rate": 0.03},
        )

        result = validator.validate(test_case, "effective_tariff_rate", year=2020)
        assert result.success
        # Should be much lower than 2025
        assert result.calculated_value < 0.05


class TestYBLDistributionalData:
    """Test distributional analysis data."""

    @pytest.fixture
    def validator(self):
        return YaleBudgetLabValidator()

    def test_tax_burden_bottom_quintile(self, validator):
        """Test tax burden for bottom quintile."""
        test_case = TestCase(
            name="Bottom quintile burden",
            inputs={},
            expected={"tax_burden_bottom_quintile": 0.02},
        )

        result = validator.validate(test_case, "tax_burden_bottom_quintile", year=2024)
        assert result.success
        # Bottom quintile has low tax burden
        assert result.calculated_value < 0.10

    def test_tax_burden_top_1pct(self, validator):
        """Test tax burden for top 1%."""
        test_case = TestCase(
            name="Top 1% burden",
            inputs={},
            expected={"tax_burden_top_1pct": 0.30},
        )

        result = validator.validate(test_case, "tax_burden_top_1pct", year=2024)
        assert result.success
        # Top 1% has higher tax burden
        assert result.calculated_value > 0.20

    def test_effective_tax_rate_by_quintile(self, validator):
        """Test effective tax rate for different quintiles."""
        # Test middle quintile (default)
        test_case = TestCase(
            name="Middle quintile effective rate",
            inputs={},
            expected={"effective_tax_rate": 0.17},
        )

        result = validator.validate(test_case, "effective_tax_rate", year=2024)
        assert result.success
        assert result.calculated_value > 0.10
        assert result.calculated_value < 0.25

        # Test top quintile
        test_case_q5 = TestCase(
            name="Top quintile effective rate",
            inputs={"income_quintile": 5},
            expected={"effective_tax_rate": 0.26},
        )

        result_q5 = validator.validate(test_case_q5, "effective_tax_rate", year=2024)
        assert result_q5.success
        # Top quintile should have higher effective rate
        assert result_q5.calculated_value > result.calculated_value


class TestYBLTaxFilingBurden:
    """Test tax filing burden data."""

    @pytest.fixture
    def validator(self):
        return YaleBudgetLabValidator()

    def test_tax_filing_time_hours(self, validator):
        """Test average tax filing time."""
        test_case = TestCase(
            name="Filing time test",
            inputs={},
            expected={"tax_filing_time_hours": 11},
        )

        result = validator.validate(test_case, "tax_filing_time_hours", year=2024)
        assert result.success
        # Average should be around 11 hours
        assert result.calculated_value > 5
        assert result.calculated_value < 20

    def test_tax_filing_time_by_complexity(self, validator):
        """Test tax filing time varies by return complexity."""
        # Simple return
        simple_case = TestCase(
            name="Simple return",
            inputs={"return_complexity": "simple"},
            expected={"tax_filing_time_hours": 3},
        )
        simple_result = validator.validate(simple_case, "tax_filing_time_hours", year=2024)

        # Complex return
        complex_case = TestCase(
            name="Complex return",
            inputs={"return_complexity": "complex"},
            expected={"tax_filing_time_hours": 20},
        )
        complex_result = validator.validate(complex_case, "tax_filing_time_hours", year=2024)

        assert simple_result.success
        assert complex_result.success
        # Complex returns should take more time
        assert complex_result.calculated_value > simple_result.calculated_value

    def test_tax_filing_cost(self, validator):
        """Test tax filing cost."""
        test_case = TestCase(
            name="Filing cost test",
            inputs={},
            expected={"tax_filing_cost": 150},
        )

        result = validator.validate(test_case, "tax_filing_cost", year=2024)
        assert result.success
        # Average cost should be around $150
        assert result.calculated_value > 50
        assert result.calculated_value < 300


class TestYBLRevenueEstimates:
    """Test revenue estimate functionality."""

    @pytest.fixture
    def validator(self):
        return YaleBudgetLabValidator()

    def test_revenue_estimate_requires_reform(self, validator):
        """Test that revenue estimates require reform specification."""
        test_case = TestCase(
            name="Revenue without reform",
            inputs={},
            expected={"revenue_estimate": 0},
        )

        result = validator.validate(test_case, "revenue_estimate", year=2024)
        assert result.calculated_value is None
        assert result.error is not None
        assert "reform" in result.error.lower()

    def test_revenue_estimate_with_reform(self, validator):
        """Test revenue estimate with reform specified."""
        test_case = TestCase(
            name="Revenue with reform",
            inputs={"reform": "trump_tariffs_2025"},
            expected={"revenue_estimate": 0},
        )

        result = validator.validate(test_case, "revenue_estimate", year=2024)
        # Should either succeed with estimate or return lookup guidance
        assert result.error is not None or result.calculated_value is not None
        if result.error:
            assert "lookup" in result.error.lower() or "manual" in result.error.lower()


class TestYBLAggregateComparison:
    """Test aggregate comparison functionality."""

    @pytest.fixture
    def validator(self):
        return YaleBudgetLabValidator()

    def test_compare_aggregates(self, validator):
        """Test comparing Cosilico aggregates to Yale Budget Lab data."""
        cosilico_aggregates = {
            "tax_burden_q1": 0.025,  # Close to YBL estimate
            "tax_burden_q5": 0.23,   # Close to YBL estimate
            "effective_tariff_rate": 0.16,  # 2025 tariff
        }

        results = validator.compare_aggregates(cosilico_aggregates, year=2025)

        assert "tax_burden_q1" in results
        assert "tax_burden_q5" in results
        assert "effective_tariff_rate" in results

        # Check result structure
        for key, comparison in results.items():
            assert "cosilico" in comparison
            assert "yale_budget_lab" in comparison
            assert "difference" in comparison
            assert "matches" in comparison

    def test_compare_aggregates_tolerance(self, validator):
        """Test that matching uses appropriate tolerance."""
        # Aggregates very close to YBL estimates
        close_aggregates = {
            "tax_burden_q3": 0.10,  # Matches YBL exactly
        }

        # Aggregates far from YBL estimates
        far_aggregates = {
            "tax_burden_q3": 0.25,  # Way off
        }

        close_results = validator.compare_aggregates(close_aggregates, year=2024)
        far_results = validator.compare_aggregates(far_aggregates, year=2024)

        # Close should match
        assert close_results["tax_burden_q3"]["matches"] is True
        # Far should not match
        assert far_results["tax_burden_q3"]["matches"] is False
