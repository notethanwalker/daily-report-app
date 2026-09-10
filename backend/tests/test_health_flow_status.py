from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]
HEALTH=(ROOT/"backend/app/routers/health_override.py").read_text(encoding="utf-8")


class HealthFlowStatusContract(unittest.TestCase):
    def test_data_health_route_is_registered(self):
        self.assertIn('@router.get("/system/data-health")',HEALTH)

    def test_flow_health_uses_persisted_evidence(self):
        self.assertIn("FlowEvent.occurred_at",HEALTH)
        self.assertIn('"recent_events_72h"',HEALTH)
        self.assertIn('"last_event_age_hours"',HEALTH)
        self.assertIn('"reachability":"not_probed_by_health_endpoint"',HEALTH)
        self.assertNotIn('"squawkflow":{"configured":True',HEALTH)


if __name__=="__main__":
    unittest.main()
