import unittest
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import MarketSnapshot, SymbolRegistry
from app.multiuser_models import PortfolioDefinition, PortfolioPosition
from app.normalized_market_models import NormalizedDailyBar
from app.services.portfolio_scenarios_v4 import _corr, _max_dd, build_buy_scenario


class PortfolioScenariosV4Test(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        Session=sessionmaker(bind=self.engine)
        self.db=Session()
        self.user="test@example.com"
        p=PortfolioDefinition(user_email=self.user,name="Test",cash=5000,is_default=True)
        self.db.add(p);self.db.flush();self.pid=p.id
        self.db.add_all([
            SymbolRegistry(symbol="AAA",name="AAA",asset_type="stock",sector="Technology",themes={"AI infrastructure":True},provider_ids={}),
            SymbolRegistry(symbol="BBB",name="BBB",asset_type="stock",sector="Financials",themes={},provider_ids={}),
            SymbolRegistry(symbol="SPY",name="SPY",asset_type="ETF",sector=None,themes={},provider_ids={}),
            SymbolRegistry(symbol="QQQ",name="QQQ",asset_type="ETF",sector=None,themes={},provider_ids={}),
            SymbolRegistry(symbol="XLK",name="XLK",asset_type="ETF",sector=None,themes={},provider_ids={}),
            PortfolioPosition(portfolio_id=p.id,symbol="BBB",shares=10,average_cost=100,imported_market_value=1000),
        ])
        now=datetime.now(timezone.utc)
        for s,px in (("AAA",50),("BBB",100),("SPY",500),("QQQ",400),("XLK",200)):
            self.db.add(MarketSnapshot(symbol=s,as_of=date.today().isoformat(),provider="test",payload={"symbol":s,"price":px},retrieved_at=now))
        start=date.today()-timedelta(days=100)
        for i in range(80):
            day=(start+timedelta(days=i)).isoformat()
            for s,base,drift in (("AAA",50,.004),("BBB",100,.001),("SPY",500,.0015),("QQQ",400,.002),("XLK",200,.0025)):
                close=base*((1+drift)**i)*(1+(i%5-2)*.001)
                self.db.add(NormalizedDailyBar(symbol=s,bar_date=day,open=close*.999,high=close*1.01,low=close*.99,close=close,volume=1_000_000,provider="test",source_url="test"))
        self.db.commit()

    def tearDown(self):
        self.db.close();self.engine.dispose()

    def test_buy_scenario_is_read_only(self):
        before=self.db.get(PortfolioDefinition,self.pid)
        cash_before=before.cash
        positions_before=self.db.query(PortfolioPosition).filter(PortfolioPosition.portfolio_id==self.pid).count()
        bbb=self.db.query(PortfolioPosition).filter_by(portfolio_id=self.pid,symbol="BBB").one();shares_before=bbb.shares
        result=build_buy_scenario(self.db,self.user,self.pid,"AAA",1000,"cash")
        self.db.expire_all()
        after=self.db.get(PortfolioDefinition,self.pid)
        bbb_after=self.db.query(PortfolioPosition).filter_by(portfolio_id=self.pid,symbol="BBB").one()
        self.assertEqual(after.cash,cash_before)
        self.assertEqual(bbb_after.shares,shares_before)
        self.assertEqual(self.db.query(PortfolioPosition).filter(PortfolioPosition.portfolio_id==self.pid).count(),positions_before)
        self.assertEqual(result["after"]["cash"],4000)
        self.assertGreater(result["after"]["symbol_exposure_percent"],result["before"]["symbol_exposure_percent"])
        self.assertEqual(result["after"]["sector"],"Technology")
        self.assertTrue(any(x["theme"]=="AI infrastructure" for x in result["theme_changes"]))

    def test_cash_funded_scenario_rejects_overspend(self):
        with self.assertRaises(ValueError):build_buy_scenario(self.db,self.user,self.pid,"AAA",6000,"cash")

    def test_risk_helpers_require_overlap_and_measure_drawdown(self):
        a={f"d{i}":i*.001 for i in range(39)};b={f"d{i}":i*.002 for i in range(39)}
        corr,n=_corr(a,b);self.assertIsNone(corr);self.assertEqual(n,39)
        self.assertLess(_max_dd({"1":.1,"2":-.2,"3":.05}),0)


if __name__=="__main__":unittest.main()
