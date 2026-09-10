import unittest

from app.services.strategy_lab_v4 import _technical_series


class StrategyLabV4Test(unittest.TestCase):
    def rows(self,n=240):
        out=[]
        for i in range(n):
            base=100+i*0.15
            out.append({"date":f"2025-{1+i//28:02d}-{1+i%28:02d}","open":base-0.5,"high":base+1.0,"low":base-1.0,"close":base,"volume":1_000_000+i*1000,"provider":"test","source_url":"test"})
        return out

    def test_future_rows_do_not_change_prior_features(self):
        rows=self.rows()
        first=_technical_series(rows[:180])[-1]
        mutated=rows[:]
        for r in mutated[180:]:
            r["close"]*=5;r["high"]*=5;r["low"]*=5;r["volume"]*=20
        second=_technical_series(mutated[:180])[-1]
        for key in ("williams_r_14","ma100","price_vs_ma100_percent","ma100_slope_20d_percent","approach_velocity_100_5d","relative_volume"):
            self.assertEqual(first[key],second[key])

    def test_technical_series_requires_past_window_before_features_exist(self):
        series=_technical_series(self.rows(130))
        self.assertIsNone(series[12]["williams_r_14"])
        self.assertIsNotNone(series[13]["williams_r_14"])
        self.assertIsNone(series[98]["ma100"])
        self.assertIsNotNone(series[99]["ma100"])
        self.assertIsNone(series[118]["ma100_slope_20d_percent"])
        self.assertIsNotNone(series[119]["ma100_slope_20d_percent"])


if __name__=="__main__":unittest.main()
