import unittest

from app.services.opportunity_criterion_governance import (
    CRITERION_GOVERNANCE,
    VALIDATION_STATUSES,
    criterion_governance,
    governed_catalog,
)
from app.services.opportunity_formula_v4 import CRITERIA


class OpportunityCriterionGovernanceTest(unittest.TestCase):
    def test_every_production_criterion_has_explicit_governance(self):
        self.assertEqual(set(CRITERIA), set(CRITERION_GOVERNANCE))
        for key in CRITERIA:
            self.assertIn(criterion_governance(key)["validation_status"], VALIDATION_STATUSES)

    def test_new_optional_factors_are_experimental(self):
        self.assertEqual(criterion_governance("ma50_proximity")["validation_status"], "experimental")
        self.assertEqual(criterion_governance("relative_volume")["validation_status"], "experimental")

    def test_default_factors_are_baseline_not_claimed_validated(self):
        for key in ("williams", "ma100_proximity", "ma100_slope", "approach_velocity"):
            governance = criterion_governance(key)
            self.assertEqual(governance["validation_status"], "baseline")
            self.assertFalse(governance["validated"])

    def test_api_catalog_preserves_canonical_label_and_surfaces_status(self):
        catalog = {item["key"]: item for item in governed_catalog(CRITERIA)}
        self.assertEqual(catalog["williams"]["canonical_label"], "Williams %R")
        self.assertIn("Baseline", catalog["williams"]["label"])
        self.assertIn("Experimental", catalog["relative_volume"]["label"])


if __name__ == "__main__":
    unittest.main()
