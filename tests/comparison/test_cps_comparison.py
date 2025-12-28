"""Tests for CPS microdata comparison against external validators."""

import pytest
import numpy as np


class TestComparisonTotals:
    """Unit tests for ComparisonTotals dataclass."""

    def test_structure(self):
        """ComparisonTotals has required fields."""
        from cosilico_validators.comparison.cps import ComparisonTotals, ModelResult

        totals = ComparisonTotals(
            variable="eitc",
            title="Earned Income Tax Credit",
            models={
                "cosilico": ModelResult("cosilico", 60e9, 100000, 100.0),
                "policyengine": ModelResult("policyengine", 62e9, 100000, 200.0),
            },
        )

        assert totals.variable == "eitc"
        assert totals.cosilico_total == 60e9
        assert totals.policyengine_total == 62e9

    def test_difference_property(self):
        """difference = cosilico - policyengine."""
        from cosilico_validators.comparison.cps import ComparisonTotals, ModelResult

        totals = ComparisonTotals(
            variable="test",
            title="Test Variable",
            models={
                "cosilico": ModelResult("cosilico", 100, 10, 50.0),
                "policyengine": ModelResult("policyengine", 80, 10, 100.0),
            },
        )

        assert totals.difference == 20

    def test_percent_difference_property(self):
        """percent_difference = (diff / pe) * 100."""
        from cosilico_validators.comparison.cps import ComparisonTotals, ModelResult

        totals = ComparisonTotals(
            variable="test",
            title="Test Variable",
            models={
                "cosilico": ModelResult("cosilico", 105, 10, 50.0),
                "policyengine": ModelResult("policyengine", 100, 10, 100.0),
            },
        )

        assert totals.percent_difference == 5.0


class TestVariableMapping:
    """Test that variable mappings are correctly defined."""

    def test_comparison_variables_has_required_keys(self):
        """Each variable mapping has cosilico_col and pe_var."""
        from cosilico_validators.comparison.cps import COMPARISON_VARIABLES

        for var_name, config in COMPARISON_VARIABLES.items():
            assert "cosilico_col" in config, f"{var_name} missing cosilico_col"
            assert "pe_var" in config, f"{var_name} missing pe_var"
            assert "title" in config, f"{var_name} missing title"

    def test_eitc_mapping(self):
        """EITC maps correctly - column derived from statute."""
        from cosilico_validators.comparison.cps import COMPARISON_VARIABLES

        assert "eitc" in COMPARISON_VARIABLES
        assert COMPARISON_VARIABLES["eitc"]["statute"] == "26/32.rac::eitc"
        assert COMPARISON_VARIABLES["eitc"]["cosilico_col"] == "eitc"  # Derived from statute
        assert COMPARISON_VARIABLES["eitc"]["pe_var"] == "eitc"


class TestCosilicoLoader:
    """Test loading Cosilico CPS calculations."""

    def test_load_returns_timed_result(self):
        """load_cosilico_cps returns TimedResult with data and timing."""
        from cosilico_validators.comparison.cps import load_cosilico_cps, TimedResult

        result = load_cosilico_cps(year=2024)

        assert isinstance(result, TimedResult)
        assert "weight" in result.data
        assert len(result.data["weight"]) > 10000  # Reasonable CPS size
        assert result.elapsed_ms > 0  # Took some time

    def test_load_includes_all_comparison_variables(self):
        """load_cosilico_cps includes all mapped variables."""
        from cosilico_validators.comparison.cps import load_cosilico_cps, COMPARISON_VARIABLES

        result = load_cosilico_cps(year=2024)

        for var_name in COMPARISON_VARIABLES:
            assert var_name in result.data, f"Missing {var_name}"
            assert len(result.data[var_name]) == len(result.data["weight"])


@pytest.mark.integration
class TestPolicyEngineLoader:
    """Test loading PolicyEngine values - requires policyengine_us."""

    def test_load_returns_dict_with_weight(self):
        """load_policyengine_values returns dict with weight array."""
        from cosilico_validators.comparison.cps import load_policyengine_values

        result = load_policyengine_values(year=2024, variables=["eitc"])

        assert isinstance(result, dict)
        assert "weight" in result
        assert "eitc" in result


@pytest.mark.integration
class TestComparison:
    """Integration tests that compare Cosilico vs PolicyEngine."""

    def test_compare_returns_dict_of_totals(self):
        """compare_cps_totals returns dict[str, ComparisonTotals]."""
        from cosilico_validators.comparison.cps import compare_cps_totals, ComparisonTotals

        result = compare_cps_totals(year=2024, variables=["eitc"])

        assert isinstance(result, dict)
        assert "eitc" in result
        assert isinstance(result["eitc"], ComparisonTotals)

    def test_totals_in_reasonable_range(self):
        """Totals should be in billions, matching IRS expectations."""
        from cosilico_validators.comparison.cps import compare_cps_totals

        result = compare_cps_totals(year=2024, variables=["eitc"])
        eitc = result["eitc"]

        # IRS reports ~$60B for EITC
        assert 30e9 < eitc.cosilico_total < 150e9
        assert 30e9 < eitc.policyengine_total < 150e9


@pytest.mark.integration
class TestDashboardExport:
    """Test dashboard export format."""

    def test_export_has_required_structure(self):
        """Dashboard export has timestamp, sections, overall."""
        from cosilico_validators.comparison.cps import compare_cps_totals, export_to_dashboard

        comparison = compare_cps_totals(year=2024, variables=["eitc"])
        dashboard = export_to_dashboard(comparison, year=2024)

        assert "timestamp" in dashboard
        assert "sections" in dashboard
        assert "overall" in dashboard

    def test_section_structure(self):
        """Each section has required fields."""
        from cosilico_validators.comparison.cps import compare_cps_totals, export_to_dashboard

        comparison = compare_cps_totals(year=2024, variables=["eitc"])
        dashboard = export_to_dashboard(comparison, year=2024)

        section = dashboard["sections"][0]
        assert "variable" in section
        assert "cosilico_total" in section
        assert "policyengine_total" in section
        assert "match_rate" in section
