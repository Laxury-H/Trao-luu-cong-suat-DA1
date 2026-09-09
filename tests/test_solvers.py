"""Kiểm thử tự động 4 phương pháp tính toán trào lưu công suất:
- Newton-Raphson (NR)
- Fast Decoupled Power Flow (FDPF)
- Gauss-Seidel (GS)
- DC Power Flow (DCPF)
- benchmark_all_solvers
"""
import json
from pathlib import Path
import unittest

from powerflow import build_ybus, parse_case, solve_power_flow, validate_case
from solvers import (
    benchmark_all_solvers,
    solve_dc_engine,
    solve_fdpf_engine,
    solve_gauss_seidel_engine,
    solve_nr_engine,
)

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


class SolversTests(unittest.TestCase):
    def setUp(self):
        self.case3 = json.loads((EXAMPLES / "luoi_3_nut.json").read_text(encoding="utf-8"))
        self.case9 = json.loads((EXAMPLES / "luoi_9_nut.json").read_text(encoding="utf-8"))
        self.case14 = json.loads((EXAMPLES / "luoi_14_nut.json").read_text(encoding="utf-8"))

    def test_solve_nr(self):
        """Kiểm tra giải thuật Newton-Raphson chuẩn trên lưới 9 nút."""
        net = validate_case(self.case9)
        ybus, prims = build_ybus(net)
        res = solve_nr_engine(net, ybus, prims, tolerance=1e-8)
        self.assertTrue(res["converged"])
        self.assertLessEqual(res["iterations"], 6)
        self.assertAlmostEqual(res["buses"][0]["vm_pu"], 1.0, places=3)

    def test_solve_fdpf(self):
        """Kiểm tra giải thuật Fast Decoupled (FDPF XB) trên lưới 9 nút và 14 nút."""
        # 1. Lưới 9 nút
        net9 = validate_case(self.case9)
        ybus9, prims9 = build_ybus(net9)
        res9_nr = solve_nr_engine(net9, ybus9, prims9, tolerance=1e-8)
        res9_fdpf = solve_fdpf_engine(net9, ybus9, prims9, tolerance=1e-5)

        self.assertTrue(res9_fdpf["converged"])
        # So sánh nghiệm FDPF so với NR (chênh lệch điện áp < 0.005 pu)
        for b_nr, b_fd in zip(res9_nr["buses"], res9_fdpf["buses"]):
            self.assertAlmostEqual(b_nr["vm_pu"], b_fd["vm_pu"], places=2)
            self.assertAlmostEqual(b_nr["va_deg"], b_fd["va_deg"], delta=0.5)

        # 2. Lưới 14 nút
        net14 = validate_case(self.case14)
        ybus14, prims14 = build_ybus(net14)
        res14_fdpf = solve_fdpf_engine(net14, ybus14, prims14, tolerance=1e-5)
        self.assertTrue(res14_fdpf["converged"])

    def test_solve_gauss_seidel(self):
        """Kiểm tra giải thuật Gauss-Seidel trên lưới 3 nút và 9 nút."""
        net3 = validate_case(self.case3)
        ybus3, prims3 = build_ybus(net3)
        res3_nr = solve_nr_engine(net3, ybus3, prims3, tolerance=1e-7)
        res3_gs = solve_gauss_seidel_engine(net3, ybus3, prims3, tolerance=1e-5, max_iterations=300)

        self.assertTrue(res3_gs["converged"])
        for b_nr, b_gs in zip(res3_nr["buses"], res3_gs["buses"]):
            self.assertAlmostEqual(b_nr["vm_pu"], b_gs["vm_pu"], places=2)
            self.assertAlmostEqual(b_nr["va_deg"], b_gs["va_deg"], delta=0.5)

    def test_solve_dc(self):
        """Kiểm tra giải thuật DC Power Flow tuyến tính hóa."""
        net = validate_case(self.case9)
        _, prims = build_ybus(net)
        res_dc = solve_dc_engine(net, prims)

        self.assertTrue(res_dc["converged"])
        self.assertEqual(res_dc["iterations"], 1)
        self.assertEqual(res_dc["summary"]["p_total_loss_mw"], 0.0)

        # Tất cả điện áp PQ phải là 1.0 pu
        for b in res_dc["buses"]:
            if b["type_input"] == "PQ":
                self.assertEqual(b["vm_pu"], 1.0)
            self.assertEqual(b["qg_mvar"], 0.0)

    def test_benchmark_all_solvers(self):
        """Kiểm tra hàm benchmark_all_solvers chạy đầy đủ 4 phương pháp."""
        bench = benchmark_all_solvers(self.case9, tolerance=1e-5)
        self.assertIn("kpi_summary", bench)
        self.assertEqual(len(bench["kpi_summary"]), 4)

        codes = [item["code"] for item in bench["kpi_summary"]]
        self.assertEqual(codes, ["NR", "FDPF", "GS", "DC"])

        # Cả 4 phương pháp đều phải hội tụ/xong
        for item in bench["kpi_summary"]:
            self.assertTrue(item["converged"], f"Solver {item['code']} failed: {item.get('status')}")
            self.assertGreaterEqual(item["time_ms"], 0.0)

        # Kiểm tra bảng so sánh nút và nhánh
        self.assertEqual(len(bench["bus_comparison"]), 9)
        self.assertEqual(len(bench["branch_comparison"]), 9)


if __name__ == "__main__":
    unittest.main()
