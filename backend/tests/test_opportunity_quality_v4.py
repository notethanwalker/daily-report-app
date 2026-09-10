import unittest
from datetime import datetime, timezone

from app.services.opportunity_quality_v4 import attach_opportunity_quality


class OpportunityQualityV4Test(unittest.TestCase):
    def test_quality_adjustment_preserves_raw_formula_score(self):
        now=datetime(2026,9,10,12,0,tzinfo=timezone.utc)
        rows=[
            {"symbol":"AAA","score":90.0,"retrieved_at":now.isoformat(),"provider":"P","verification_status":"verified","source_url":"https://example.com/a"},
            {"symbol":"BBB","score":90.0,"retrieved_at":now.isoformat(),"provider":"P","verification_status":"primary_only","source_url":"https://example.com/b"},
        ]
        attach_opportunity_quality(rows,now=now)
        self.assertEqual(rows[0]["score"],90.0)
        self.assertEqual(rows[1]["score"],90.0)
        by_symbol={r["symbol"]:r for r in rows}
        self.assertGreater(by_symbol["AAA"]["quality_confidence"],by_symbol["BBB"]["quality_confidence"])
        self.assertGreater(by_symbol["AAA"]["quality_adjusted_score"],by_symbol["BBB"]["quality_adjusted_score"])
        self.assertEqual(by_symbol["AAA"]["quality_adjusted_rank"],1)
        self.assertEqual(by_symbol["BBB"]["quality_adjusted_rank"],2)


if __name__=="__main__":unittest.main()
