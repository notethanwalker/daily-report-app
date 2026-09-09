from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[2]
OP=(ROOT/'web/app/v4/opportunity-table-v4.tsx').read_text()
MAC=(ROOT/'web/app/v4/macro-rotation-table-v4.tsx').read_text()
CSS=(ROOT/'web/app/v4/v4.css').read_text()
class StrengthColorContract(unittest.TestCase):
    def test_opportunity_strength_scale(self):
        self.assertIn('opportunityTone',OP)
        self.assertIn('strength-strong',OP)
        self.assertIn('strength-weak',OP)
    def test_macro_strength_scale(self):
        self.assertIn('macroTone',MAC)
        self.assertIn('leading_accelerating',MAC)
        self.assertIn('lagging_deteriorating',MAC)
    def test_visual_classes_exist(self):
        for x in ('strength-strong','strength-positive','strength-negative','strength-weak'):
            self.assertIn(x,CSS)
if __name__=='__main__':unittest.main()
