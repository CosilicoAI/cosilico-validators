"""Tests for microdata validation module.

Tests follow TDD - write failing test first, then fix.
"""

import numpy as np
import pytest
from pathlib import Path


class TestFilingStatusComparison:
    """Test that filing status comparisons work correctly in DSL formulas."""

    def test_joint_threshold_uses_250k(self):
        """JOINT filers should use $250k threshold for NIIT."""
        import sys
        sys.path.insert(0, str(Path.home() / "CosilicoAI/cosilico-engine/src"))

        from cosilico.vectorized_executor import (
            VectorizedExecutor, VectorizedContext, EntityIndex
        )
        from cosilico.dsl_executor import get_default_parameters

        # NIIT formula with string literals for filing status
        code = '''
        variable net_investment_income_tax {
          entity TaxUnit
          period Year
          dtype Money

          formula {
            let threshold = if filing_status == "JOINT" then
              250000
            else if filing_status == "SEPARATE" then
              125000
            else
              200000

            let excess_magi = max(0, adjusted_gross_income - threshold)
            let nii = interest_income + dividend_income
            let taxable_amount = min(nii, excess_magi)

            return 0.038 * taxable_amount
          }
        }
        '''

        # Test case: JOINT filer with AGI below $250k threshold
        # Should have $0 NIIT
        inputs = {
            'filing_status': np.array(['JOINT', 'SINGLE', 'JOINT']),
            'adjusted_gross_income': np.array([211371, 211371, 300000]),
            'interest_income': np.array([5000, 5000, 5000]),
            'dividend_income': np.array([5000, 5000, 5000]),
        }

        entity_index = EntityIndex(
            person_to_tax_unit=np.array([0, 1, 2]),  # 1:1 for simplicity
            tax_unit_to_household=np.array([0, 1, 2]),
            n_persons=3,
            n_tax_units=3,
            n_households=3,
        )

        executor = VectorizedExecutor(parameters=get_default_parameters())
        results = executor.execute(
            code=code,
            inputs=inputs,
            entity_index=entity_index,
            output_variables=['net_investment_income_tax'],
        )

        niit = results['net_investment_income_tax']

        # JOINT with AGI=$211,371 < $250k threshold: NIIT = $0
        assert niit[0] == pytest.approx(0, abs=1), \
            f"JOINT filer with AGI=$211,371 should have $0 NIIT, got ${niit[0]:.0f}"

        # SINGLE with AGI=$211,371 > $200k threshold: NIIT > $0
        # excess = 211371 - 200000 = 11371
        # taxable = min(10000, 11371) = 10000
        # tax = 0.038 * 10000 = 380
        assert niit[1] == pytest.approx(380, abs=1), \
            f"SINGLE filer with AGI=$211,371 should have ~$380 NIIT, got ${niit[1]:.0f}"

        # JOINT with AGI=$300k > $250k threshold: NIIT > $0
        # excess = 300000 - 250000 = 50000
        # taxable = min(10000, 50000) = 10000
        # tax = 0.038 * 10000 = 380
        assert niit[2] == pytest.approx(380, abs=1), \
            f"JOINT filer with AGI=$300k should have ~$380 NIIT, got ${niit[2]:.0f}"

    def test_separate_threshold_uses_125k(self):
        """SEPARATE filers should use $125k threshold for NIIT."""
        import sys
        sys.path.insert(0, str(Path.home() / "CosilicoAI/cosilico-engine/src"))

        from cosilico.vectorized_executor import (
            VectorizedExecutor, VectorizedContext, EntityIndex
        )
        from cosilico.dsl_executor import get_default_parameters

        # NIIT thresholds per §1411(b) - SURVIVING_SPOUSE gets $250k like JOINT
        code = '''
        variable test_threshold {
          entity TaxUnit
          period Year
          dtype Money

          formula {
            let threshold = if filing_status == "JOINT" then
              250000
            else if filing_status == "SURVIVING_SPOUSE" then
              250000
            else if filing_status == "SEPARATE" then
              125000
            else
              200000
            return threshold
          }
        }
        '''

        inputs = {
            'filing_status': np.array([
                'JOINT', 'SEPARATE', 'SINGLE', 'HEAD_OF_HOUSEHOLD', 'SURVIVING_SPOUSE'
            ]),
        }

        entity_index = EntityIndex(
            person_to_tax_unit=np.array([0, 1, 2, 3, 4]),
            tax_unit_to_household=np.array([0, 1, 2, 3, 4]),
            n_persons=5,
            n_tax_units=5,
            n_households=5,
        )

        executor = VectorizedExecutor(parameters=get_default_parameters())
        results = executor.execute(
            code=code,
            inputs=inputs,
            entity_index=entity_index,
            output_variables=['test_threshold'],
        )

        threshold = results['test_threshold']

        assert threshold[0] == 250000, f"JOINT should be $250k, got ${threshold[0]}"
        assert threshold[1] == 125000, f"SEPARATE should be $125k, got ${threshold[1]}"
        assert threshold[2] == 200000, f"SINGLE should be $200k, got ${threshold[2]}"
        assert threshold[3] == 200000, f"HOH should be $200k, got ${threshold[3]}"
        # §1411(b)(1) explicitly includes surviving spouse in $250k bracket
        assert threshold[4] == 250000, f"SURVIVING_SPOUSE should be $250k, got ${threshold[4]}"


class TestEntityAggregation:
    """Test person -> tax_unit aggregation."""

    def test_sum_members_aggregates_correctly(self):
        """sum(members, variable) should aggregate person values to tax unit."""
        import sys
        sys.path.insert(0, str(Path.home() / "CosilicoAI/cosilico-engine/src"))

        from cosilico.vectorized_executor import (
            VectorizedExecutor, EntityIndex
        )
        from cosilico.dsl_executor import get_default_parameters

        code = '''
        variable total_income {
          entity TaxUnit
          period Year
          dtype Money

          formula {
            return sum(members, person_income)
          }
        }
        '''

        # 4 persons in 2 tax units
        # TU0: persons 0, 1 (incomes 1000, 2000) -> total 3000
        # TU1: persons 2, 3 (incomes 3000, 4000) -> total 7000
        inputs = {
            'person_income': np.array([1000, 2000, 3000, 4000]),
        }

        entity_index = EntityIndex(
            person_to_tax_unit=np.array([0, 0, 1, 1]),
            tax_unit_to_household=np.array([0, 1]),
            n_persons=4,
            n_tax_units=2,
            n_households=2,
        )

        executor = VectorizedExecutor(parameters=get_default_parameters())
        results = executor.execute(
            code=code,
            inputs=inputs,
            entity_index=entity_index,
            output_variables=['total_income'],
        )

        total = results['total_income']
        assert len(total) == 2, f"Should have 2 tax units, got {len(total)}"
        assert total[0] == 3000, f"TU0 should be $3000, got ${total[0]}"
        assert total[1] == 7000, f"TU1 should be $7000, got ${total[1]}"


class TestMicrodataValidatorIntegration:
    """Integration tests for the full validation pipeline."""

    @pytest.mark.skip(reason="CosilicoCalculator entity index handling needs work")
    def test_niit_matches_policyengine_above_threshold(self):
        """NIIT should match PE for cases where AGI > threshold."""
        from cosilico_validators.microdata import (
            PolicyEngineMicrodataSource,
            CosilicoCalculator,
            PolicyEngineCalculator,
        )

        source = PolicyEngineMicrodataSource(year=2024)
        cosilico = CosilicoCalculator()
        pe = PolicyEngineCalculator()

        cos_result = cosilico.calculate('niit', source)
        pe_result = pe.calculate('niit', source)

        assert cos_result.success, f"Cosilico failed: {cos_result.error}"
        assert pe_result.success, f"PE failed: {pe_result.error}"

        # For high-income cases (AGI > threshold), should match closely
        agi = source.get_variable('adjusted_gross_income')
        fs = source.get_variable('filing_status')

        # Get threshold for each tax unit per §1411(b)
        # JOINT and SURVIVING_SPOUSE get $250k, SEPARATE gets $125k, others get $200k
        threshold = np.where(
            (fs == 'JOINT') | (fs == 'SURVIVING_SPOUSE'), 250000,
            np.where(fs == 'SEPARATE', 125000, 200000)
        )

        high_income_mask = agi > threshold + 10000  # Well above threshold

        cos_high = cos_result.values[high_income_mask]
        pe_high = pe_result.values[high_income_mask]

        diff = np.abs(cos_high - pe_high)
        match_rate = (diff <= 15).mean()

        assert match_rate >= 0.95, \
            f"High-income NIIT match rate should be >=95%, got {match_rate:.1%}"
