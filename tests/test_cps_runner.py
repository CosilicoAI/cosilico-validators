"""Tests for CPS validation runner."""

import pytest
import numpy as np
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cosilico_validators.cps.runner import (
    CPSValidationRunner,
    VariableConfig,
    ValidationResult,
    ComparisonResult,
)


class TestVariableConfig:
    """Tests for VariableConfig dataclass."""

    def test_basic_config(self):
        """Test creating a basic variable config."""
        config = VariableConfig(
            name="ctc",
            section="26/24",
            title="Child Tax Credit",
            cosilico_file="26/24/a/credit.cosilico",
            cosilico_variable="child_tax_credit",
            pe_variable="ctc",
            taxsim_variable="v22",
        )
        assert config.name == "ctc"
        assert config.tolerance == 15.0  # default

    def test_custom_tolerance(self):
        """Test custom tolerance."""
        config = VariableConfig(
            name="test",
            section="1/2",
            title="Test",
            cosilico_file="test.cosilico",
            cosilico_variable="test_var",
            pe_variable="test",
            tolerance=5.0,
        )
        assert config.tolerance == 5.0


class TestComparisonResult:
    """Tests for ComparisonResult dataclass."""

    def test_perfect_match(self):
        """Test result with perfect match."""
        result = ComparisonResult(
            validator="policyengine",
            n_compared=100,
            n_matches=100,
            match_rate=1.0,
            mean_absolute_error=0.0,
        )
        assert result.match_rate == 1.0
        assert result.n_matches == 100

    def test_partial_match(self):
        """Test result with partial match."""
        result = ComparisonResult(
            validator="taxsim",
            n_compared=100,
            n_matches=95,
            match_rate=0.95,
            mean_absolute_error=5.5,
            mismatches=[{"index": 0, "cosilico": 100, "validator": 110}],
        )
        assert result.match_rate == 0.95
        assert len(result.mismatches) == 1


class TestCPSValidationRunner:
    """Tests for CPSValidationRunner."""

    def test_initialization_defaults(self):
        """Test default initialization."""
        runner = CPSValidationRunner()
        assert runner.year == 2024
        assert runner.tolerance == 15.0
        assert runner.dataset == "enhanced_cps"

    def test_initialization_custom(self):
        """Test custom initialization."""
        runner = CPSValidationRunner(
            year=2023,
            tolerance=10.0,
            dataset="cps_2023",
        )
        assert runner.year == 2023
        assert runner.tolerance == 10.0

    def test_variables_configured(self):
        """Test that default variables are configured."""
        variables = CPSValidationRunner.get_variables()
        var_names = [v.name for v in variables]
        assert "ctc" in var_names
        assert "eitc" in var_names
        assert "standard_deduction" in var_names
        assert "snap" in var_names

    def test_ctc_config(self):
        """Test CTC variable configuration."""
        variables = CPSValidationRunner.get_variables()
        ctc = next(v for v in variables if v.name == "ctc")
        assert ctc.section == "26/24"
        assert ctc.pe_variable == "ctc"
        assert ctc.taxsim_variable == "v22"
        assert "credit.cosilico" in ctc.cosilico_file


class TestComparison:
    """Tests for value comparison logic."""

    def test_compare_identical_arrays(self):
        """Test comparing identical arrays."""
        runner = CPSValidationRunner()
        a = np.array([100.0, 200.0, 300.0])
        b = np.array([100.0, 200.0, 300.0])

        result = runner._compare(a, b, "test")
        assert result.match_rate == 1.0
        assert result.n_matches == 3
        assert result.mean_absolute_error == 0.0

    def test_compare_within_tolerance(self):
        """Test comparing arrays within tolerance."""
        runner = CPSValidationRunner(tolerance=15.0)
        a = np.array([100.0, 200.0, 300.0])
        b = np.array([110.0, 205.0, 290.0])  # All within $15

        result = runner._compare(a, b, "test")
        assert result.match_rate == 1.0
        assert result.n_matches == 3

    def test_compare_outside_tolerance(self):
        """Test comparing arrays outside tolerance."""
        runner = CPSValidationRunner(tolerance=15.0)
        a = np.array([100.0, 200.0, 300.0])
        b = np.array([120.0, 200.0, 300.0])  # First is $20 off

        result = runner._compare(a, b, "test")
        assert result.match_rate == pytest.approx(2/3)
        assert result.n_matches == 2
        assert len(result.mismatches) == 1

    def test_compare_records_mismatches(self):
        """Test that mismatches are properly recorded."""
        runner = CPSValidationRunner(tolerance=10.0)
        a = np.array([100.0, 200.0])
        b = np.array([150.0, 200.0])

        result = runner._compare(a, b, "test")
        assert len(result.mismatches) == 1
        assert result.mismatches[0]["index"] == 0
        assert result.mismatches[0]["cosilico"] == 100.0
        assert result.mismatches[0]["validator"] == 150.0
        assert result.mismatches[0]["difference"] == 50.0


class TestCosilicoPaths:
    """Tests for Cosilico file path handling."""

    def test_default_cosilico_path(self):
        """Test default cosilico-us path."""
        runner = CPSValidationRunner()
        expected = Path.home() / "CosilicoAI/cosilico-us"
        assert runner.cosilico_us_path == expected

    def test_custom_cosilico_path(self):
        """Test custom cosilico-us path."""
        custom_path = Path("/tmp/cosilico-us")
        runner = CPSValidationRunner(cosilico_us_path=custom_path)
        assert runner.cosilico_us_path == custom_path


def _pe_available() -> bool:
    """Check if policyengine-us is available."""
    try:
        from policyengine_us import Microsimulation
        return True
    except ImportError:
        return False


def _cosilico_engine_available() -> bool:
    """Check if cosilico-engine is available."""
    try:
        engine_path = Path.home() / "CosilicoAI/cosilico-engine/src"
        sys.path.insert(0, str(engine_path))
        from cosilico.vectorized_executor import VectorizedExecutor
        return True
    except ImportError:
        return False


class TestIntegration:
    """Integration tests (require policyengine-us)."""

    @pytest.mark.skipif(
        not _pe_available(),
        reason="policyengine-us not installed"
    )
    def test_pe_simulation_loads(self):
        """Test that PolicyEngine simulation loads."""
        runner = CPSValidationRunner()
        sim = runner._get_pe_simulation()
        assert sim is not None

    @pytest.mark.skipif(
        not _pe_available(),
        reason="policyengine-us not installed"
    )
    def test_extract_inputs(self):
        """Test extracting inputs from PE simulation."""
        runner = CPSValidationRunner()
        inputs = runner._extract_inputs_from_pe()

        # Should have standard input variables
        assert "age" in inputs
        assert "earned_income" in inputs
        assert "filing_status" in inputs


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
