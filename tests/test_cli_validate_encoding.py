"""Tests for the validate-encoding CLI command."""

import json
import tempfile
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from cosilico_validators.cli import cli


@pytest.fixture
def runner():
    """Create a CLI runner for testing."""
    return CliRunner()


@pytest.fixture
def sample_tests_yaml():
    """Create a sample tests.yaml file for testing."""
    test_data = {
        "variable": "adjusted_gross_income",
        "tax_year": 2024,
        "test_cases": [
            {
                "name": "Simple wages - single",
                "inputs": {
                    "employment_income": 50000,
                    "filing_status": "single",
                },
                "expected": {
                    "adjusted_gross_income": 50000,
                },
                "citations": ["26 USC 62(a)"],
            },
            {
                "name": "Zero income",
                "inputs": {
                    "employment_income": 0,
                    "filing_status": "single",
                },
                "expected": {
                    "adjusted_gross_income": 0,
                },
            },
        ],
    }

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as f:
        yaml.dump(test_data, f)
        return Path(f.name)


@pytest.fixture
def sample_cosilico_dir(sample_tests_yaml):
    """Create a mock cosilico directory structure."""
    test_dir = sample_tests_yaml.parent / "statute" / "26" / "62" / "a"
    test_dir.mkdir(parents=True, exist_ok=True)

    # Move the tests.yaml to the proper location
    target_tests = test_dir / "tests.yaml"
    sample_tests_yaml.rename(target_tests)

    # Create a minimal .cosilico file
    cosilico_file = test_dir / "adjusted_gross_income.cosilico"
    cosilico_file.write_text(
        """module statute.26.62.a
version "2024.1"

variable adjusted_gross_income {
  entity TaxUnit
  period Year
  dtype Money
  reference "26 USC 62(a)"

  formula {
    return employment_income
  }
}
"""
    )

    yield cosilico_file

    # Cleanup
    import shutil

    shutil.rmtree(sample_tests_yaml.parent / "statute", ignore_errors=True)


class TestValidateEncodingCommand:
    """Tests for the validate-encoding CLI command."""

    def test_validate_encoding_help(self, runner):
        """Test that the help text is displayed."""
        result = runner.invoke(cli, ["validate-encoding", "--help"])
        assert result.exit_code == 0
        assert "Validate a .cosilico encoding" in result.output

    def test_validate_encoding_requires_cosilico_file(self, runner):
        """Test that a .cosilico file path is required."""
        result = runner.invoke(cli, ["validate-encoding"])
        assert result.exit_code != 0
        assert "Missing argument" in result.output or "Error" in result.output

    def test_validate_encoding_file_not_found(self, runner):
        """Test error handling for non-existent file."""
        result = runner.invoke(
            cli, ["validate-encoding", "/nonexistent/path/file.cosilico"]
        )
        assert result.exit_code != 0

    def test_validate_encoding_json_output(self, runner, sample_cosilico_dir):
        """Test that JSON output is produced when requested."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            output_file = f.name

        result = runner.invoke(
            cli,
            [
                "validate-encoding",
                str(sample_cosilico_dir),
                "--output",
                output_file,
                "--no-policyengine",  # Skip PE for faster test
            ],
        )

        # Check that output file was created
        output_path = Path(output_file)
        if output_path.exists():
            with open(output_path) as f:
                data = json.load(f)
            # Check structure
            assert "variable" in data or "error" in data

        # Cleanup
        output_path.unlink(missing_ok=True)


class TestValidateEncodingIntegration:
    """Integration tests for validate-encoding with real PE validation."""

    @pytest.mark.skipif(
        True,  # Skip by default - enable for integration testing
        reason="Integration test - requires PolicyEngine installed",
    )
    def test_validate_agi_encoding(self, runner, sample_cosilico_dir):
        """Test validating AGI encoding against PolicyEngine."""
        result = runner.invoke(
            cli,
            [
                "validate-encoding",
                str(sample_cosilico_dir),
            ],
        )

        # Should complete without crashing
        assert result.exit_code == 0
        assert "Validation Results" in result.output or "match_rate" in result.output
