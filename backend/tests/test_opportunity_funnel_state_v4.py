import unittest

from app.services.opportunity_funnel_state_v4 import diff_transitions


class OpportunityFunnelStateV4Test(unittest.TestCase):
    def test_stage_change_is_recorded(self):
        previous={"AAOI":{"stage":"developing","formula_rank":4}}
        current={"AAOI":{"stage":"actionable","formula_rank":3,"priority_rank":2,"formula_score":78.4}}
        changes=diff_transitions(previous,current,"2026-09-10T00:00:00Z")
        self.assertEqual(len(changes),1)
        self.assertEqual(changes[0]["from"],"developing")
        self.assertEqual(changes[0]["to"],"actionable")

    def test_new_candidate_is_not_false_transition(self):
        changes=diff_transitions({}, {"NBIS":{"stage":"watch"}}, "2026-09-10T00:00:00Z")
        self.assertEqual(changes,[])

    def test_removed_candidate_is_recorded(self):
        previous={"MU":{"stage":"watch","formula_rank":40}}
        changes=diff_transitions(previous,{},"2026-09-10T00:00:00Z")
        self.assertEqual(changes[0]["to"],"out_of_shortlist")


if __name__ == "__main__":
    unittest.main()
