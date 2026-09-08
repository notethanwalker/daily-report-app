import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/daily-report-v4-tests.db")

from app.services.classification_v4 import rotation_exposures, rotation_proxy_name
from app.services.feature_model_v4 import MODEL_CONFIG_HASH, MODEL_VERSION, presentation_payload, version_payload
from app.services.rotation_model_v4 import _observation_age_hours, _state
from app.services.opportunity_scanner import _bucket


class RotationStateTests(unittest.TestCase):
    def test_leading_accelerating(self):self.assertEqual(_state(2.0,0.8,4.0),("leading_accelerating","inflow_candidate"))
    def test_leading_weakening(self):self.assertEqual(_state(2.0,-0.8,4.0),("leading_weakening","rotation_out_risk"))
    def test_lagging_improving(self):self.assertEqual(_state(-2.0,0.8,-3.0),("lagging_improving","early_rotation_candidate"))
    def test_observation_date_can_make_recent_retrieval_stale(self):
        now=datetime(2026,9,8,20,tzinfo=timezone.utc);row=SimpleNamespace(retrieved_at=datetime(2026,9,8,19,tzinfo=timezone.utc),as_of="2026-09-01")
        self.assertGreater(_observation_age_hours(row,{"as_of":"2026-09-01"},now),72)

class CandidateSetupTests(unittest.TestCase):
    def test_strong_williams_and_100ma_setup(self):self.assertEqual(_bucket(-85.0,2.0),"strong")
    def test_below_100ma_is_not_entry_setup(self):self.assertIsNone(_bucket(-90.0,-1.0))

class ClassificationTests(unittest.TestCase):
    def test_memory_override_beats_broad_technology(self):self.assertEqual(rotation_proxy_name("MU","Technology","Semiconductors",{}),("Memory","symbol_weighted_override"))
    def test_memory_has_weighted_exposure(self):
        ex,basis=rotation_exposures("MU","Technology","Semiconductors",{})
        self.assertAlmostEqual(sum(ex.values()),1.0);self.assertGreater(ex["Memory"],ex["Semiconductors"]);self.assertEqual(basis,"symbol_weighted_override")
    def test_industry_mapping_beats_sector(self):
        proxy,basis=rotation_proxy_name("XYZ","Technology","Semiconductor Equipment",{})
        self.assertEqual(proxy,"Semiconductors");self.assertEqual(basis,"industry_or_theme")

class FeatureVersionTests(unittest.TestCase):
    def test_version_payload_is_stable_and_non_destructive(self):
        payload=version_payload({"buy_score":75.0});self.assertEqual(payload["buy_score"],75.0);self.assertEqual(payload["model_version"],MODEL_VERSION);self.assertEqual(payload["model_config_hash"],MODEL_CONFIG_HASH)
    def test_pre_cutover_snapshot_remains_legacy(self):
        payload=presentation_payload({"buy_score":60.0},"2026-09-07");self.assertEqual(payload["model_version"],"legacy_unversioned");self.assertIsNone(payload["model_config_hash"])
    def test_post_cutover_snapshot_can_use_current_version(self):self.assertEqual(presentation_payload({"buy_score":60.0},"2026-09-08")["model_version"],MODEL_VERSION)

if __name__=="__main__":unittest.main()
