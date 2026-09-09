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


if __name__ == "__main__":
    unittest.main()
