from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]
FORMULA=(ROOT/"web/app/v4/opportunity-formula-v4.css").read_text(encoding="utf-8")
FUNNEL=(ROOT/"web/app/v4/opportunity-candidate-funnel-v4.css").read_text(encoding="utf-8")
FIXES=(ROOT/"web/app/v4-fixes.css").read_text(encoding="utf-8")


class MobileV4Contract(unittest.TestCase):
    def test_formula_index_does_not_force_desktop_width_on_phone(self):
        phone=FORMULA[FORMULA.index("@media(max-width:600px)"):]
        self.assertIn(".opportunity-index-row.header{display:none}",phone)
        self.assertIn(".opportunity-index-table{overflow:visible}",phone)
        self.assertNotIn("min-width:760px",phone)

    def test_candidate_funnel_does_not_force_wide_mobile_cards(self):
        mobile=FUNNEL[FUNNEL.index("@media(max-width:800px)"):]
        self.assertIn(".funnel-candidate{min-width:0}",mobile)
        self.assertIn(".funnel-candidate-list{overflow:visible}",mobile)
        self.assertNotIn("min-width:700px",mobile)

    def test_iphone_subtabs_and_scroll_are_vertical_document_native(self):
        self.assertIn(".subtab-bar,.subtab-bar.compact{grid-template-columns:1fr!important}",FIXES)
        self.assertIn("max-height:none!important;overflow-y:visible!important",FIXES)
        self.assertIn(".price-chart{min-width:100%!important;width:100%!important",FIXES)
        self.assertIn("min-height:44px",FIXES)


if __name__=="__main__":
    unittest.main()
