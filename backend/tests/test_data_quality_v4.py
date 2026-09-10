import unittest
from datetime import datetime, timezone

from app.services.data_quality_v4 import build_quality_summary, confidence_adjusted_score, confidence_multiplier, normalize_verification


class DataQualityV4Test(unittest.TestCase):
    def test_verification_taxonomy_is_explicit(self):
        self.assertEqual(normalize_verification("verified"),"cross_checked")
        self.assertEqual(normalize_verification("primary_only"),"primary_only")
        self.assertEqual(normalize_verification("discrepancy"),"discrepant")
        self.assertEqual(normalize_verification(None),"unverified")

    def test_full_fresh_cross_checked_quality_is_high(self):
        sections={k:{"available":True,"fresh":True} for k in ("fundamentals","news","catalysts","filings","flow")}
        q=build_quality_summary(sections=sections,required_sections=list(sections),verification_status="verified",feature_status="available")
        self.assertEqual(q["state"],"verified")
        self.assertEqual(q["completeness"],1.0)
        self.assertEqual(q["freshness"],1.0)
        self.assertGreaterEqual(q["confidence"],0.9)

    def test_missing_and_primary_only_degrade_without_erasing_score(self):
        sections={"market":{"available":True,"fresh":True},"fundamentals":{"available":False,"fresh":False}}
        q=build_quality_summary(sections=sections,required_sections=["market","fundamentals"],verification_status="primary_only",feature_status="available")
        self.assertLess(q["confidence"],0.9)
        self.assertTrue(any(p["code"]=="fundamentals_missing" for p in q["problems"]))
        self.assertTrue(any(p["code"]=="verification_primary_only" for p in q["problems"]))
        raw=90.0;adjusted=confidence_adjusted_score(raw,q["confidence"])
        self.assertEqual(raw,90.0)
        self.assertLess(adjusted,raw)
        self.assertGreaterEqual(confidence_multiplier(q["confidence"]),0.5)

    def test_sources_include_age_without_claiming_missing_timestamp(self):
        now=datetime(2026,9,10,12,0,tzinfo=timezone.utc)
        q=build_quality_summary(sections={},required_sections=[],verification_status="not_applicable",feature_status="not_applicable",source_rows=[{"provider":"X","retrieved_at":"2026-09-10T11:00:00+00:00"},{"provider":"Y"}],now=now)
        self.assertEqual(q["sources"][0]["age_minutes"],60.0)
        self.assertIsNone(q["sources"][1]["age_minutes"])


if __name__=="__main__":unittest.main()
