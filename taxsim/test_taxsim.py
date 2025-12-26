"""Tests for TaxSim validation infrastructure.

Run with: pytest taxsim/test_taxsim.py -v
"""

import pytest
from pathlib import Path

from .taxsim_client import TaxSimCase, TaxSimClient, TaxSimResult, create_test_case
from .taxsim_comparison import TaxSimComparison, ComparisonResult, ValidationReport
from .variable_mapping import (
    TAXSIM_TO_COSILICO,
    COSILICO_TO_TAXSIM,
    map_taxsim_to_cosilico,
    map_cosilico_to_taxsim,
    get_filing_status_code,
    get_state_code,
)


class TestVariableMapping:
    """Tests for variable mapping functions."""

    def test_taxsim_to_cosilico_mapping_exists(self):
        """Verify key mappings exist."""
        assert "v10" in TAXSIM_TO_COSILICO
        assert "v25" in TAXSIM_TO_COSILICO
        assert "fiitax" in TAXSIM_TO_COSILICO

    def test_map_taxsim_to_cosilico(self):
        """Test mapping TaxSim variables to Cosilico."""
        assert map_taxsim_to_cosilico("v10") == "adjusted_gross_income"
        assert map_taxsim_to_cosilico("v25") == "earned_income_credit"
        assert map_taxsim_to_cosilico("v22") == "child_tax_credit"
        assert map_taxsim_to_cosilico("fiitax") == "total_federal_income_tax"

    def test_map_cosilico_to_taxsim(self):
        """Test mapping Cosilico variables to TaxSim."""
        assert map_cosilico_to_taxsim("adjusted_gross_income") == "v10"
        assert map_cosilico_to_taxsim("earned_income_credit") == "v25"
        assert map_cosilico_to_taxsim("eitc") == "v25"  # Test alias

    def test_get_filing_status_code(self):
        """Test filing status to mstat conversion."""
        assert get_filing_status_code("SINGLE") == 1
        assert get_filing_status_code("JOINT") == 2
        assert get_filing_status_code("MARRIED_FILING_JOINTLY") == 2
        assert get_filing_status_code("HEAD_OF_HOUSEHOLD") == 6
        assert get_filing_status_code("HOH") == 6
        assert get_filing_status_code("SEPARATE") == 8

    def test_get_state_code(self):
        """Test state abbreviation to FIPS conversion."""
        assert get_state_code("CA") == 6
        assert get_state_code("NY") == 36
        assert get_state_code("TX") == 48
        assert get_state_code("XX") == 0  # Unknown state


class TestTaxSimCase:
    """Tests for TaxSimCase creation and conversion."""

    def test_basic_case_creation(self):
        """Test creating a basic TaxSimCase."""
        case = TaxSimCase(
            year=2023,
            filing_status="SINGLE",
            primary_wages=50000,
        )
        assert case.year == 2023
        assert case.filing_status == "SINGLE"
        assert case.primary_wages == 50000

    def test_case_to_taxsim_dict(self):
        """Test converting case to TaxSim input format."""
        case = TaxSimCase(
            year=2023,
            filing_status="JOINT",
            primary_age=40,
            spouse_age=38,
            primary_wages=75000,
            spouse_wages=45000,
            num_dependents=2,
            child_ages=[10, 8],
        )

        taxsim_dict = case.to_taxsim_dict()

        assert taxsim_dict["year"] == 2023
        assert taxsim_dict["mstat"] == 2  # JOINT
        assert taxsim_dict["page"] == 40
        assert taxsim_dict["sage"] == 38
        assert taxsim_dict["pwages"] == 75000
        assert taxsim_dict["swages"] == 45000
        assert taxsim_dict["depx"] == 2
        assert taxsim_dict["age1"] == 10
        assert taxsim_dict["age2"] == 8
        assert taxsim_dict["idtl"] == 2  # Full output

    def test_case_from_dict(self):
        """Test creating case from dictionary."""
        data = {
            "year": 2023,
            "filing_status": "SINGLE",
            "earned_income": 30000,
            "num_children": 1,
        }

        case = TaxSimCase.from_dict(data)

        assert case.year == 2023
        assert case.filing_status == "SINGLE"
        assert case.primary_wages == 30000
        assert case.num_dependents == 1

    def test_create_test_case_helper(self):
        """Test the create_test_case convenience function."""
        case = create_test_case(
            earned_income=40000,
            filing_status="JOINT",
            num_children=2,
            year=2023,
            age=35,
        )

        assert case.primary_wages == 40000
        assert case.filing_status == "JOINT"
        assert case.num_dependents == 2
        assert case.spouse_age == 35  # Set for joint filers
        assert len(case.child_ages) == 2


class TestTaxSimResult:
    """Tests for TaxSimResult handling."""

    def test_result_success(self):
        """Test successful result properties."""
        result = TaxSimResult(
            taxsimid=1,
            year=2023,
            raw_output={"v10": 50000, "v25": 0},
            cosilico_output={"adjusted_gross_income": 50000, "earned_income_credit": 0},
        )

        assert result.success
        assert result.get("adjusted_gross_income") == 50000
        assert result.get("v10") == 50000

    def test_result_error(self):
        """Test error result properties."""
        result = TaxSimResult(
            taxsimid=1,
            year=2023,
            raw_output={},
            cosilico_output={},
            error="Connection failed",
        )

        assert not result.success
        assert result.error == "Connection failed"


class TestComparisonResult:
    """Tests for comparison result generation."""

    def test_comparison_result_match(self):
        """Test comparison result when values match."""
        result = ComparisonResult(
            case_name="Test Case",
            variable="adjusted_gross_income",
            cosilico_value=50000,
            taxsim_value=50000,
            difference=0,
            percent_difference=0,
            within_tolerance=True,
            tolerance=1.0,
        )

        assert result.matches
        assert result.difference == 0

    def test_comparison_result_mismatch(self):
        """Test comparison result when values differ."""
        result = ComparisonResult(
            case_name="Test Case",
            variable="earned_income_credit",
            cosilico_value=600,
            taxsim_value=580,
            difference=20,
            percent_difference=3.45,
            within_tolerance=False,
            tolerance=1.0,
        )

        assert not result.matches
        assert result.difference == 20


class TestTaxSimComparison:
    """Tests for TaxSimComparison engine."""

    def test_load_test_cases(self):
        """Test loading test cases from YAML."""
        yaml_path = Path(__file__).parent / "test_cases.yaml"
        if yaml_path.exists():
            comparison = TaxSimComparison()
            cases = comparison.load_test_cases(yaml_path)

            assert len(cases) > 0
            assert all(isinstance(c, TaxSimCase) for c in cases)

    def test_comparison_with_mock_calculator(self):
        """Test comparison engine with a mock Cosilico calculator."""
        # Mock calculator that returns fixed values
        def mock_calc(case: TaxSimCase, variables: list) -> dict:
            return {
                "adjusted_gross_income": case.primary_wages + case.spouse_wages,
                "earned_income_credit": 0,
            }

        comparison = TaxSimComparison(
            cosilico_calculator=mock_calc,
            variables=["adjusted_gross_income", "earned_income_credit"],
            tolerance=1.0,
        )

        case = TaxSimCase(
            year=2023,
            filing_status="SINGLE",
            primary_wages=50000,
        )

        # Create mock TaxSim result
        taxsim_result = TaxSimResult(
            taxsimid=1,
            year=2023,
            raw_output={"v10": 50000, "v25": 0},
            cosilico_output={"adjusted_gross_income": 50000, "earned_income_credit": 0},
        )

        case_result = comparison.compare_case(case, taxsim_result)

        assert case_result.all_match
        assert case_result.match_count == 2
        assert case_result.mismatch_count == 0


class TestValidationReport:
    """Tests for validation report generation."""

    def test_report_summary(self):
        """Test validation report summary calculation."""
        from .taxsim_comparison import CaseComparisonResult

        case_result = CaseComparisonResult(
            case_name="Test",
            case_inputs={},
            variable_results={
                "agi": ComparisonResult(
                    case_name="Test",
                    variable="agi",
                    cosilico_value=50000,
                    taxsim_value=50000,
                    difference=0,
                    percent_difference=0,
                    within_tolerance=True,
                    tolerance=1.0,
                )
            },
            all_match=True,
            match_count=1,
            mismatch_count=0,
            error_count=0,
        )

        report = ValidationReport(
            title="Test Report",
            generated_at="2023-01-01",
            taxsim_version="TAXSIM-35",
            year=2023,
            tolerance=1.0,
            case_results=[case_result],
        )

        assert report.summary["total_cases"] == 1
        assert report.summary["cases_matching"] == 1
        assert report.summary["case_match_rate"] == 1.0

    def test_report_to_markdown(self):
        """Test markdown report generation."""
        from .taxsim_comparison import CaseComparisonResult

        case_result = CaseComparisonResult(
            case_name="Single Filer",
            case_inputs={"pwages": 50000},
            variable_results={
                "adjusted_gross_income": ComparisonResult(
                    case_name="Single Filer",
                    variable="adjusted_gross_income",
                    cosilico_value=50000,
                    taxsim_value=50000,
                    difference=0,
                    percent_difference=0,
                    within_tolerance=True,
                    tolerance=1.0,
                )
            },
            all_match=True,
            match_count=1,
            mismatch_count=0,
            error_count=0,
        )

        report = ValidationReport(
            title="TaxSim Validation",
            generated_at="2023-01-01",
            taxsim_version="TAXSIM-35",
            year=2023,
            tolerance=1.0,
            case_results=[case_result],
        )

        markdown = report.to_markdown()

        assert "# TaxSim Validation" in markdown
        assert "Single Filer" in markdown
        assert "PASS" in markdown


# Integration tests (require network access)
@pytest.mark.integration
class TestTaxSimClientIntegration:
    """Integration tests that actually call the TaxSim API."""

    def test_simple_calculation(self):
        """Test a simple calculation against TaxSim API."""
        client = TaxSimClient(timeout=30)

        case = TaxSimCase(
            year=2023,
            filing_status="SINGLE",
            primary_age=35,
            primary_wages=50000,
        )

        result = client.calculate(case)

        # Should succeed
        assert result.success, f"TaxSim call failed: {result.error}"

        # Should have AGI
        agi = result.get("adjusted_gross_income")
        assert agi is not None, "AGI not in results"
        assert agi > 0, f"AGI should be positive, got {agi}"

    def test_batch_calculation(self):
        """Test batch calculation against TaxSim API."""
        client = TaxSimClient(timeout=60)

        cases = [
            TaxSimCase(taxsimid=1, year=2023, filing_status="SINGLE", primary_wages=30000),
            TaxSimCase(taxsimid=2, year=2023, filing_status="JOINT", primary_wages=60000, spouse_wages=40000),
        ]

        results = client.calculate_batch(cases)

        assert len(results) == 2
        for result in results:
            assert result.success, f"Batch call failed: {result.error}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
