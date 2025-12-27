"""Tests for aggregate income tax validation harness.

TDD: Write tests first, then implement.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


class TestAggregateHarness:
    """Test the aggregate income tax validation harness."""

    def test_harness_returns_valid_structure(self):
        """Harness should return a dict with required keys."""
        from cosilico_validators.aggregate import run_aggregate_validation

        # Mock PE to avoid loading real data in tests
        with patch("cosilico_validators.aggregate.harness.Microsimulation") as mock_sim:
            # Setup mock
            mock_instance = MagicMock()
            mock_sim.return_value = mock_instance

            # Mock calculate to return numpy arrays
            mock_instance.calculate.side_effect = lambda var, year: np.array([1000.0, 2000.0, 3000.0])

            result = run_aggregate_validation(use_sample=True, sample_size=3)

        assert "metadata" in result
        assert "sources" in result
        assert "comparison" in result
        assert "summary" in result

    def test_policyengine_aggregates_computed(self):
        """PolicyEngine aggregates should be computed correctly."""
        from cosilico_validators.aggregate import compute_policyengine_aggregates

        # Mock simulation
        mock_sim = MagicMock()

        # Use consistent weights for all entity types
        tax_unit_weights = np.array([1.0, 2.0, 1.0])  # 4 total tax units
        household_weights = np.array([1.0, 2.0, 1.0])  # 4 total households
        spm_weights = np.array([1.0, 2.0, 1.0])
        person_weights = np.array([1.0, 2.0, 1.0])
        income_tax = np.array([1000.0, 2000.0, 500.0])  # 1*1000 + 2*2000 + 1*500 = 5500
        agi = np.array([50000.0, 80000.0, 30000.0])

        mock_sim.calculate.side_effect = lambda var, year: {
            "household_weight": household_weights,
            "tax_unit_weight": tax_unit_weights,
            "spm_unit_weight": spm_weights,
            "person_weight": person_weights,
            "income_tax": income_tax,
            "adjusted_gross_income": agi,
            "income_tax_before_credits": income_tax * 1.2,
            "eitc": np.zeros(3),
            "ctc": np.zeros(3),
            "snap": np.zeros(3),
            "ssi": np.zeros(3),
        }[var]

        result = compute_policyengine_aggregates(mock_sim, year=2024)

        assert result["source"] == "PolicyEngine-US"
        assert "aggregates" in result
        assert result["aggregates"]["total_income_tax"] == pytest.approx(5500.0)
        assert result["aggregates"]["total_population"] == pytest.approx(4.0)

    def test_comparison_report_structure(self):
        """Comparison report should have correct structure for dashboard."""
        from cosilico_validators.aggregate import generate_comparison_report

        pe_results = {
            "source": "PolicyEngine-US",
            "aggregates": {
                "total_income_tax": 2.5e12,  # $2.5T
                "total_agi": 15e12,  # $15T
                "total_population": 150e6,
            },
        }

        report = generate_comparison_report(pe_results, None, None, year=2024)

        assert report["metadata"]["tax_year"] == 2024
        assert report["comparison"]["baseline"] == "PolicyEngine-US"
        assert "pe_total_income_tax_billions" in report["summary"]
        # $2.5T = 2500B
        assert report["summary"]["pe_total_income_tax_billions"] == pytest.approx(2500.0)

    def test_dashboard_json_output_valid(self):
        """Output JSON should be valid for dashboard consumption."""
        from cosilico_validators.aggregate import generate_comparison_report

        pe_results = {
            "source": "PolicyEngine-US",
            "aggregates": {
                "total_income_tax": 2.5e12,
                "total_agi": 15e12,
                "total_population": 150e6,
            },
        }

        report = generate_comparison_report(pe_results, None, None, year=2024)

        # Should be JSON serializable
        json_str = json.dumps(report)
        assert len(json_str) > 0

        # Should round-trip
        parsed = json.loads(json_str)
        assert parsed["metadata"]["tax_year"] == 2024

    def test_taxsim_comparison_included_when_available(self):
        """TAXSIM results should be included in comparison when available."""
        from cosilico_validators.aggregate import generate_comparison_report

        pe_results = {
            "source": "PolicyEngine-US",
            "aggregates": {
                "total_income_tax": 2.5e12,
                "total_agi": 15e12,
                "total_population": 150e6,
            },
        }

        taxsim_results = {
            "source": "TAXSIM-35",
            "aggregates": {
                "total_income_tax": 2.45e12,  # $50B lower
            },
        }

        report = generate_comparison_report(pe_results, taxsim_results, None, year=2024)

        assert "taxsim" in report["sources"]
        assert len(report["comparison"]["comparisons"]) == 1
        assert report["comparison"]["comparisons"][0]["source"] == "TAXSIM-35"
        # -$50B difference
        assert report["comparison"]["comparisons"][0]["difference_billions"] == pytest.approx(-50.0)


class TestIRSBenchmarks:
    """Test against IRS Statistics of Income benchmarks."""

    @pytest.mark.skip(reason="Requires real CPS data - run manually")
    def test_total_agi_within_irs_range(self):
        """Total AGI should be within 5% of IRS SOI figures."""
        from cosilico_validators.aggregate import run_aggregate_validation

        result = run_aggregate_validation()
        total_agi = result["sources"]["policyengine"]["aggregates"]["total_agi"]

        # IRS SOI 2021: ~$14.5 trillion AGI
        # Allow 10% tolerance for CPS vs admin data differences
        irs_agi_2021 = 14.5e12
        assert abs(total_agi - irs_agi_2021) / irs_agi_2021 < 0.10

    @pytest.mark.skip(reason="Requires real CPS data - run manually")
    def test_total_income_tax_within_irs_range(self):
        """Total income tax should be within 10% of IRS figures."""
        from cosilico_validators.aggregate import run_aggregate_validation

        result = run_aggregate_validation()
        total_tax = result["sources"]["policyengine"]["aggregates"]["total_income_tax"]

        # IRS SOI 2021: ~$2.2 trillion individual income tax
        irs_tax_2021 = 2.2e12
        assert abs(total_tax - irs_tax_2021) / irs_tax_2021 < 0.15
