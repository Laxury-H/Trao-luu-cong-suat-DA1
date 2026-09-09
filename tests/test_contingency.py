"""Kiểm thử mô-đun phân tích sự cố N-1 (contingency.py)."""
from pathlib import Path
import unittest

from contingency import run_n1_contingency_analysis
from powerflow import load_case

ROOT = Path(__file__).resolve().parents[1]


class ContingencyTests(unittest.TestCase):
    def test_n1_contingency_3_bus(self):
        case_3 = load_case(ROOT / "examples" / "luoi_3_nut.json")
        res = run_n1_contingency_analysis(case_3)
        self.assertEqual(res["total_contingencies"], 3)
        self.assertIn("contingencies", res)
        self.assertEqual(len(res["contingencies"]), 3)

        # Kiểm tra tính sắp xếp theo PI giảm dần
        scores = [c["pi_score"] for c in res["contingencies"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_n1_contingency_14_bus(self):
        case_14 = load_case(ROOT / "examples" / "luoi_14_nut.json")
        res = run_n1_contingency_analysis(case_14, tolerance=1e-5)
        self.assertEqual(res["total_contingencies"], 20)
        self.assertGreater(res["total_contingencies"], 0)
        self.assertIn("worst_contingency", res)

        # Kiểm tra cấu trúc bản ghi từng kịch bản
        first = res["contingencies"][0]
        self.assertIn("branch_id", first)
        self.assertIn("severity", first)
        self.assertIn("pi_score", first)
        self.assertIn("max_loading", first)
        self.assertIn("min_voltage", first)


if __name__ == "__main__":
    unittest.main()
