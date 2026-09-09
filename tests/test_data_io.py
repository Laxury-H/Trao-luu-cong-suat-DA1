"""Kiểm thử nhập/xuất dữ liệu Excel (.xlsx) và CSV, cùng trình nhập liệu bảng TableInputEditor."""
from pathlib import Path
import tempfile
import unittest

from data_io import (
    create_sample_excel_template,
    export_case_to_excel,
    export_full_results_to_excel,
    load_from_csv,
    load_from_excel,
)
from powerflow import load_case, solve_power_flow
from ui_table_editor import TableInputEditor

ROOT = Path(__file__).resolve().parents[1]


class DataIoTests(unittest.TestCase):
    def test_excel_roundtrip_3_bus(self):
        case_3 = load_case(ROOT / "examples" / "luoi_3_nut.json")
        with tempfile.TemporaryDirectory() as d:
            excel_path = Path(d) / "luoi_3_nut.xlsx"
            export_case_to_excel(case_3, excel_path)
            self.assertTrue(excel_path.exists())

            loaded = load_from_excel(excel_path)
            self.assertEqual(len(loaded["buses"]), len(case_3["buses"]))
            self.assertEqual(len(loaded["branches"]), len(case_3["branches"]))

            res_orig = solve_power_flow(case_3)
            res_loaded = solve_power_flow(loaded)
            self.assertTrue(res_loaded["converged"])
            self.assertEqual(res_loaded["iterations"], res_orig["iterations"])
            self.assertAlmostEqual(res_loaded["summary"]["pg_total_mw"], res_orig["summary"]["pg_total_mw"], places=4)

    def test_excel_roundtrip_9_bus(self):
        case_9 = load_case(ROOT / "examples" / "luoi_9_nut.json")
        with tempfile.TemporaryDirectory() as d:
            excel_path = Path(d) / "luoi_9_nut.xlsx"
            export_case_to_excel(case_9, excel_path)
            loaded = load_from_excel(excel_path)
            self.assertEqual(len(loaded["buses"]), 9)
            self.assertEqual(len(loaded["branches"]), 9)

            res = solve_power_flow(loaded)
            self.assertTrue(res["converged"])
            self.assertEqual(res["iterations"], 4)

    def test_sample_template_generation_and_solving(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sample.xlsx"
            create_sample_excel_template(p)
            self.assertTrue(p.exists())
            case = load_from_excel(p)
            self.assertEqual(len(case["buses"]), 3)
            res = solve_power_flow(case)
            self.assertTrue(res["converged"])

    def test_table_editor_methods(self):
        case = load_case(ROOT / "examples" / "luoi_3_nut.json")
        editor = TableInputEditor(None)
        editor.set_case_data(case)
        self.assertEqual(len(editor.buses_data), 3)
        self.assertEqual(len(editor.branches_data), 3)

        retrieved = editor.get_case_data()
        self.assertEqual(len(retrieved["buses"]), 3)
        self.assertEqual(len(retrieved["branches"]), 3)
        editor.destroy()

    def test_export_full_results_to_excel(self):
        case = load_case(ROOT / "examples" / "luoi_3_nut.json")
        res = solve_power_flow(case)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "full_report.xlsx"
            export_full_results_to_excel(res, p)
            self.assertTrue(p.exists())


if __name__ == "__main__":
    unittest.main()
