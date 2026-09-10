import unittest
from datetime import datetime, timezone

from app.services.world_news_synthesis_v4 import classify_article, importance_score, map_exposure, synthesize_world_news


class WorldNewsSynthesisV4Test(unittest.TestCase):
    def test_classifies_macro_categories_deterministically(self):
        article={"title":"Fed rate decision lifts Treasury yields as inflation remains firm"}
        categories=classify_article(article)
        self.assertIn("monetary_policy",categories)
        self.assertIn("inflation_growth",categories)

    def test_exposure_mapping_is_association_only(self):
        mapped=map_exposure({"title":"Nvidia and semiconductor export restrictions expand"})
        self.assertIn("NVDA",mapped["tickers"])
        self.assertIn("Semiconductors",mapped["themes"])
        self.assertEqual(mapped["causal_confidence"],"association_only")
        self.assertIn("headline_keyword",mapped["mapping_basis"])

    def test_recent_systemic_story_scores_above_generic_old_story(self):
        now=datetime(2026,9,10,13,0,tzinfo=timezone.utc)
        recent={"title":"Federal Reserve rate decision changes Treasury yields","published_at":"2026-09-10T12:00:00+00:00","relevance_score":70,"sectors":["Financials"]}
        old={"title":"Company updates business plans","published_at":"2026-09-04T12:00:00+00:00","relevance_score":70,"sectors":[]}
        self.assertGreater(importance_score(recent,now),importance_score(old,now))

    def test_effects_are_explicitly_hypotheses_and_stories_have_timelines(self):
        payload={"provider":"test","articles":[
            {"title":"Oil prices rise after supply disruption","url":"a","domain":"A","published_at":"2026-09-10T10:00:00+00:00","relevance_score":70,"sectors":["Energy"]},
            {"title":"Oil rises as supply disruption deepens","url":"b","domain":"B","published_at":"2026-09-10T11:00:00+00:00","relevance_score":72,"sectors":["Energy"]},
        ]}
        result=synthesize_world_news(payload)
        self.assertTrue(result["articles"])
        self.assertEqual(result["articles"][0]["effect_status"],"hypothesis")
        self.assertIn("not claims",result["articles"][0]["effect_policy"])
        self.assertTrue(result["stories"])
        self.assertTrue(result["stories"][0]["timeline"])


if __name__=="__main__":unittest.main()
