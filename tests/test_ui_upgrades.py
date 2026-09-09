"""Kiểm thử các tính năng UI/UX mới: Sơ đồ đơn tuyến, Dark Theme, Xuất CSV, KPI bổ sung."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from gui import PowerFlowApp, EXAMPLES
from powerflow import load_case, solve_power_flow
from ui_topology import NetworkDiagram

ROOT = Path(__file__).resolve().parents[1]


class UiUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.dialogs = {}
        for name in ("showerror", "showinfo", "showwarning", "askyesnocancel"):
            self.dialogs[name] = self.enterContext(patch(f"gui.messagebox.{name}", return_value=None))
        self.save_dialog = self.enterContext(patch("gui.filedialog.asksaveasfilename", return_value=""))
        self.app = PowerFlowApp()
        self.app.withdraw()
        self.addCleanup(self.app.destroy)
        self.pump()

    def pump(self):
        self.app.update()

    def wait_until(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.pump()
            time.sleep(0.01)
        self.pump()
        self.assertTrue(predicate(), "Chờ quá thời gian")

    def calculate(self):
        self.app.calculate()
        self.wait_until(lambda: not self.app.is_running)
        self.assertIsNotNone(self.app.result)
        return self.app.result

    def test_theme_toggle(self):
        """Kiểm tra chuyển đổi giao diện Sáng / Tối."""
        self.assertEqual(self.app.theme_mode, "light")
        self.app.toggle_theme()
        self.pump()
        self.assertEqual(self.app.theme_mode, "dark")
        self.assertEqual(self.app.dashboard.theme_mode, "dark")
        self.assertEqual(self.app.diagram.theme_mode, "dark")
        self.assertEqual(self.app.json_editor.theme_mode, "dark")

        # Chuyển ngược lại về Sáng
        self.app.toggle_theme()
        self.pump()
        self.assertEqual(self.app.theme_mode, "light")
        self.assertEqual(self.app.dashboard.theme_mode, "light")
        self.assertEqual(self.app.diagram.theme_mode, "light")

    def test_network_diagram_rendering(self):
        """Kiểm tra sơ đồ 1 sợi cập nhật khi giải và tương tác."""
        result = self.calculate()
        diagram = self.app.diagram
        self.assertIsNotNone(diagram.result)
        self.assertEqual(len(diagram.bus_coords), len(result["buses"]))

        # Kiểm tra zoom và reset
        initial_scale = diagram.scale
        diagram._zoom_in()
        self.assertGreater(diagram.scale, initial_scale)
        diagram._zoom_out()
        diagram.reset_layout()
        self.assertEqual(diagram.scale, 1.0)

        # Kiểm tra giả lập kéo thả nút
        bus_id = str(result["buses"][0]["id"])
        x_before, y_before = diagram.bus_coords[bus_id]
        diagram._dragging_bus = bus_id
        diagram._drag_offset_x = 100
        diagram._drag_offset_y = 100

        class DummyEvent:
            x = 120
            y = 130
        diagram._on_canvas_drag(DummyEvent())
        x_after, y_after = diagram.bus_coords[bus_id]
        self.assertNotEqual((x_before, y_before), (x_after, y_after))
        diagram._on_canvas_release(DummyEvent())
        self.assertIsNone(diagram._dragging_bus)

    def test_additional_kpis(self):
        """Kiểm tra các chỉ số KPI mới: % tổn thất và hệ số cos phi."""
        self.calculate()
        loss_pct_str = self.app.dashboard.metric_values["loss_pct"].get()
        pf_str = self.app.dashboard.metric_values["power_factor"].get()
        self.assertTrue(loss_pct_str.endswith("%"))
        self.assertNotIn("—", loss_pct_str)
        self.assertNotIn("—", pf_str)
        pf = float(pf_str)
        self.assertGreaterEqual(pf, 0.0)
        self.assertLessEqual(pf, 1.0)

    def test_csv_export(self):
        """Kiểm tra xuất kết quả ra file CSV."""
        self.calculate()
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "result.csv"
            self.save_dialog.return_value = str(destination)
            self.app.export("csv")
            self.assertTrue(destination.exists())
            content = destination.read_text(encoding="utf-8-sig")
            self.assertIn("BẢNG ĐIỆN ÁP VÀ CÔNG SUẤT NÚT", content)
            self.assertIn("BẢNG CÔNG SUẤT VÀ TỔN THẤT NHÁNH", content)
            self.assertIn("SLACK", content)


    def test_force_layout_and_large_network(self):
        """Kiểm tra thuật toán bố cục tự động và lưới 30 nút."""
        self.app.load_example("luoi_30_nut.json")
        res = self.calculate()
        self.assertEqual(len(res["buses"]), 30)
        diagram = self.app.diagram
        self.assertEqual(len(diagram.bus_coords), 30)

        # Kiểm tra Force layout
        diagram.apply_force_layout()
        self.assertEqual(len(diagram.bus_coords), 30)

        # Kiểm tra Concentric layout
        diagram.apply_concentric_layout()
        self.assertEqual(len(diagram.bus_coords), 30)

        # Kiểm tra Fit to view
        diagram.fit_to_view()
        self.assertGreater(diagram.scale, 0.0)

        # Kiểm tra chế độ chọn tiêu điểm nút
        diagram._find_bus_at = lambda x, y: "10"
        class ClickEvent:
            x = 100
            y = 100
        diagram._on_canvas_press(ClickEvent())
        self.assertEqual(diagram.selected_bus, "10")
        diagram._clear_selection()
        self.assertIsNone(diagram.selected_bus)

    def test_n1_contingency_tab_and_execution(self):
        """Kiểm tra tab quét sự cố N-1 và đồng bộ kết quả lên bảng & thẻ KPI."""
        from contingency import run_n1_contingency_analysis
        from powerflow import parse_case

        self.app.load_example("luoi_14_nut.json")
        self.calculate()

        data = parse_case(self.app.text())
        n1_res = run_n1_contingency_analysis(data)

        self.app._on_n1_finished(n1_res, None)
        self.assertEqual(self.app.n1_cards["total"]["text"], str(n1_res["total_contingencies"]))
        self.assertEqual(self.app.n1_cards["safe"]["text"], str(n1_res["secure_count"]))

        # Kiểm tra các dòng bảng N-1
        children = self.app.n1_table.get_children()
        self.assertEqual(len(children), n1_res["total_contingencies"])

        # Kiểm tra sắp xếp theo PI
        self.app.sort_n1_table("pi_score")
        new_children = self.app.n1_table.get_children()
        self.assertEqual(len(new_children), n1_res["total_contingencies"])
        first_row = self.app.n1_table.item(new_children[0], "values")
        self.assertTrue(len(first_row) >= 5)

        # Kiểm tra xem trên sơ đồ
        self.app.n1_table.selection_set(new_children[0])
        self.app.view_contingency_on_diagram()
        self.assertIsNotNone(self.app.diagram.selected_bus)

    def test_scenario_compare_tab(self):
        """Kiểm tra chế độ so sánh kịch bản Base Case và kịch bản mới."""
        from powerflow import parse_case

        self.app.load_example("luoi_3_nut.json")
        self.calculate()

        # Lưu làm Base Case
        self.app.set_as_base_case()
        self.assertIsNotNone(self.app.base_case_result)
        self.assertIn("Base Case:", self.app.base_case_info.get())

        # Thay đổi tải và tính lại
        parsed = parse_case(self.app.text())
        for b in parsed["buses"]:
            if b["id"] == 3:
                b["pd_mw"] = 90.0  # Tăng gấp đôi tải nút 3
        import json
        self.app.editor.delete("1.0", "end")
        self.app.editor.insert("1.0", json.dumps(parsed))
        self.calculate()

        # Kiểm tra bảng so sánh đã được tính toán sai khác
        bus_rows = self.app.compare_bus_table.get_children()
        self.assertEqual(len(bus_rows), 3)

        branch_rows = self.app.compare_branch_table.get_children()
        self.assertEqual(len(branch_rows), 3)

        # Biến thiên tổn thất phải hiển thị giá trị khác 0
        loss_text = self.app.compare_cards["loss_delta"]["text"]
        self.assertIn("MW", loss_text)

        # Xóa Base Case
        self.app.clear_base_case()
        self.assertIsNone(self.app.base_case_result)
        self.assertEqual(len(self.app.compare_bus_table.get_children()), 0)

    def test_topology_voltage_hierarchy_and_search(self):
        """Kiểm tra bố cục phân tầng cấp điện áp và định vị tìm kiếm nút."""
        self.app.load_example("luoi_14_nut.json")
        self.calculate()

        diagram = self.app.diagram
        diagram.apply_voltage_hierarchy_layout()
        self.assertEqual(len(diagram.bus_coords), 14)

        # Kiểm tra tìm kiếm và định vị nút hợp lệ
        success = diagram.locate_bus("8")
        self.assertTrue(success)
        self.assertEqual(diagram.selected_bus, "8")

        # Kiểm tra tìm nút không tồn tại
        failed = diagram.locate_bus("9999")
        self.assertFalse(failed)

    def test_solver_selection_and_execution(self):
        """Kiểm tra chọn phương pháp giải trên giao diện và tính toán."""
        # 1. Giải bằng FDPF
        self.app.solver_method.set("Phân tách nhanh (FDPF)")
        self.pump()
        res_fdpf = self.calculate()
        self.assertIn("FDPF", res_fdpf.get("solver_method", ""))

        # 2. Giải bằng DC Flow
        self.app.solver_method.set("Trào lưu một chiều (DC Flow)")
        self.pump()
        res_dc = self.calculate()
        self.assertIn("DC", res_dc.get("solver_method", ""))

        # 3. Trả về Newton-Raphson
        self.app.solver_method.set("Newton–Raphson (Chuẩn CN)")
        self.pump()
        res_nr = self.calculate()
        self.assertIn("Newton-Raphson", res_nr.get("solver_method", ""))

    def test_solvers_benchmark_tab_execution_and_export(self):
        """Kiểm tra tab đối chiếu 4 phương pháp và xuất kết quả."""
        self.app.run_solvers_benchmark()
        self.wait_until(lambda: self.app.btn_run_benchmark["text"] == "🚀 Chạy so sánh cả 4 phương pháp")

        # Kiểm tra bảng KPI có đủ 4 phương pháp
        kpi_items = self.app.bench_kpi_table.get_children()
        self.assertEqual(len(kpi_items), 4)

        # Kiểm tra bảng nút và bảng nhánh
        bus_items = self.app.bench_bus_table.get_children()
        self.assertEqual(len(bus_items), 3)

        branch_items = self.app.bench_branch_table.get_children()
        self.assertEqual(len(branch_items), 3)

        # Kiểm tra xuất file CSV
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            with patch("gui.filedialog.asksaveasfilename", return_value=tmp_path):
                self.app.export_solvers_benchmark()
            content = Path(tmp_path).read_text(encoding="utf-8-sig")
            self.assertIn("Newton-Raphson", content)
            self.assertIn("FDPF", content)
            self.assertIn("Gauss-Seidel", content)
            self.assertIn("DC", content)
        finally:
            Path(tmp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
