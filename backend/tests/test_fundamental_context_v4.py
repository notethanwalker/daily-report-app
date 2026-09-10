import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.services.fundamental_assessment_v4 import MODEL_VERSION
from app.services.fundamental_context_v4 import assessment_history, persist_assessment_snapshot, _percentile
from app.v4_models import FundamentalAssessmentSnapshotV4


class FundamentalContextV4Test(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session=sessionmaker(bind=self.engine)
        self.db=self.Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def payload(self, pe=18.0):
        return {
            "provider":"test",
            "retrieved_at":datetime.now(timezone.utc).isoformat(),
            "eps":5.0,
            "pe_ratio":pe,
            "price_to_sales_ratio":3.0,
            "peg_ratio":1.1,
            "quarterly_revenue_growth_yoy":.2,
            "quarterly_earnings_growth_yoy":.2,
            "profit_margin":.18,
            "return_on_equity":.2,
            "free_cash_flow":1_000_000,
            "debt_to_equity":40,
        }

    def test_same_day_snapshot_is_idempotent(self):
        persist_assessment_snapshot(self.db,"TEST",self.payload(18),commit=True)
        persist_assessment_snapshot(self.db,"TEST",self.payload(20),commit=True)
        rows=self.db.query(FundamentalAssessmentSnapshotV4).filter(FundamentalAssessmentSnapshotV4.symbol=="TEST").all()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0].model_version,MODEL_VERSION)

    def test_history_requires_real_multiple_date_observations(self):
        persist_assessment_snapshot(self.db,"TEST",self.payload(),commit=True)
        first=assessment_history(self.db,"TEST")
        self.assertFalse(first["available"])
        self.assertEqual(first["observations"],1)
        self.db.add(FundamentalAssessmentSnapshotV4(symbol="TEST",observation_date="2026-09-09",quality_score=70,valuation_score=65,anomaly="neutral",payload={},model_version=MODEL_VERSION))
        self.db.commit()
        second=assessment_history(self.db,"TEST")
        self.assertTrue(second["available"])
        self.assertEqual(second["observations"],2)
        self.assertIn("No historical valuation is reconstructed",second["policy"])

    def test_percentile_midrank_handles_ties(self):
        self.assertEqual(_percentile(20,[10,20,20,30]),50.0)
        self.assertIsNone(_percentile(None,[1,2]))
        self.assertIsNone(_percentile(1,[]))


if __name__=="__main__":
    unittest.main()
