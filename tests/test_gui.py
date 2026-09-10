"""UI state regressions with a real, withdrawn Tk window and mocked dialogs."""
import json
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from gui import PowerFlowApp
from powerflow import PowerFlowError, parse_case, solve_power_flow


class PowerFlowGuiTests(unittest.TestCase):
    def setUp(self):
        self.dialogs = {}
        for name in ("showerror", "showinfo", "showwarning", "askyesnocancel"):
            self.dialogs[name] = self.enterContext(patch(f"gui.messagebox.{name}", return_value=None))
        self.open_dialog = self.enterContext(patch("gui.filedialog.askopenfilename", return_value=""))
        self.save_dialog = self.enterContext(patch("gui.filedialog.asksaveasfilename", return_value=""))
        for attempt in range(3):
            try:
                self.app = PowerFlowApp()
                break
            except tk.TclError as exc:
                if "no display name" in str(exc) or "couldn't connect to display" in str(exc):
                    self.skipTest(f"Tk display unavailable: {exc}")
                if attempt == 2:
                    raise
                time.sleep(0.2)
        self.app.withdraw()
        self.addCleanup(self.app.destroy)
        self.callback_errors = []
        self.app.report_callback_exception = lambda _kind, error, _tb: self.callback_errors.append(error)
        self.pump()

    def pump(self):
        self.app.update()
        if self.callback_errors:
            raise self.callback_errors.pop(0)

    def wait_until(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.pump()
            time.sleep(0.01)
        self.pump()
        self.assertTrue(predicate(), "Timed out while waiting for the GUI worker")

    def calculate(self):
        self.app.calculate()
        self.wait_until(lambda: not self.app.is_running)
        self.assertIsNotNone(self.app.result, self.app.status.get())
        return self.app.result

    def edit(self, text):
        self.app.editor.delete("1.0", "end")
        self.app.editor.insert("1.0", text)
        self.pump()

    def assert_export_disabled(self):
        self.assertTrue(self.app.export_buttons)
        self.assertTrue(all(button.instate(["disabled"]) for button in self.app.export_buttons))

    def test_successful_solve_publishes_tables_and_exports_json(self):
        self.assertIsNone(self.app.result)
        self.assert_export_disabled()
        result = self.calculate()
        self.assertTrue(result["converged"])
        self.assertEqual(self.app.result_source, self.app.signature())
        self.assertEqual(len(self.app.bus_table.get_children()), len(result["buses"]))
        self.assertEqual(len(self.app.branch_table.get_children()), len(result["branches"]))
        self.assertTrue(all(not button.instate(["disabled"]) for button in self.app.export_buttons))
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "result.json"
            self.save_dialog.return_value = str(destination)
            self.app.export("json")
            self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), result)

    def test_editor_change_clears_results_and_prevents_export(self):
        self.calculate()
        self.edit(self.app.text() + "\n")
        self.assertIsNone(self.app.result)
        self.assertIsNone(self.app.result_source)
        self.assertEqual(self.app.bus_table.get_children(), ())
        self.assertEqual(self.app.branch_table.get_children(), ())
        self.assert_export_disabled()
        self.app.export("json")
        self.save_dialog.assert_not_called()

    def test_solver_option_change_invalidates_result(self):
        for variable, value in ((self.app.tolerance, "1e-7"),
                                (self.app.max_iter, "75"),
                                (self.app.enforce_q, False)):
            with self.subTest(option=variable):
                self.calculate()
                variable.set(value)
                self.pump()
                self.assertIsNone(self.app.result)
                self.assertIsNone(self.app.result_source)
                self.assert_export_disabled()

    def test_edit_during_solve_discards_worker_result_and_repeat_is_guarded(self):
        started, release = threading.Event(), threading.Event()
        original_data = parse_case(self.app.text())
        result = solve_power_flow(original_data)

        def slow_solver(*_args, **_kwargs):
            started.set()
            if not release.wait(5):
                raise RuntimeError("Test did not release worker")
            return result

        with patch("gui.solve_power_flow", side_effect=slow_solver) as solver:
            try:
                self.app.calculate()
                self.wait_until(started.is_set)
                self.assertTrue(self.app.is_running)
                self.assertTrue(self.app.run_button.instate(["disabled"]))
                self.app.calculate()
                self.assertEqual(solver.call_count, 1)
                self.edit(self.app.text() + "\n")
            finally:
                release.set()
                self.wait_until(lambda: not self.app.is_running)
        self.assertIsNone(self.app.result)
        self.assertIsNone(self.app.result_source)
        self.assertFalse(self.app.run_button.instate(["disabled"]))
        self.assert_export_disabled()
        self.app.export("json")
        self.save_dialog.assert_not_called()

    def test_invalid_solver_options_are_reported_inline_without_starting_worker(self):
        for tolerance, iterations in (("nan", "50"), ("inf", "50"), ("0", "50"),
                                      ("1e-8", "0"), ("1e-8", "1.5")):
            with self.subTest(tolerance=tolerance, iterations=iterations):
                self.app.tolerance.set(tolerance)
                self.app.max_iter.set(iterations)
                with patch("gui.threading.Thread") as worker:
                    self.app.calculate()
                    worker.assert_not_called()
                self.assertFalse(self.app.is_running)
                self.assertIsNone(self.app.result)
                self.assertTrue(self.app.input_feedback.get().strip())
                self.assertFalse(self.app.run_button.instate(["disabled"]))
        self.dialogs["showerror"].assert_not_called()

    def test_solver_failure_releases_running_state_and_allows_retry(self):
        with patch("gui.solve_power_flow", side_effect=PowerFlowError("Không hội tụ trong số bước cho phép")):
            self.app.calculate()
            self.wait_until(lambda: not self.app.is_running)
        self.assertIsNone(self.app.result)
        self.assertFalse(self.app.run_button.instate(["disabled"]))
        self.assert_export_disabled()
        self.calculate()

    def test_invalid_json_validation_preserves_editor_and_reports_line_inline(self):
        text = '{\n  "base_mva": ,\n  "buses": []\n}'
        self.edit(text)
        self.app.validate_input()
        self.assertEqual(self.app.text(), text)
        feedback = self.app.input_feedback.get().lower()
        self.assertIn("dòng", feedback)
        self.assertIn("2", feedback)
        self.dialogs["showerror"].assert_not_called()

    def test_clean_document_does_not_prompt_for_discard(self):
        self.assertEqual(self.app.saved_text, self.app.text())
        self.assertTrue(self.app.confirm_discard())
        self.dialogs["askyesnocancel"].assert_not_called()

    def test_dirty_discard_cancel_and_discard_keep_current_text_until_replaced(self):
        self.edit(self.app.text() + "\n")
        text = self.app.text()
        self.dialogs["askyesnocancel"].return_value = None
        self.assertFalse(self.app.confirm_discard())
        self.assertEqual(self.app.text(), text)
        self.dialogs["askyesnocancel"].return_value = False
        self.assertTrue(self.app.confirm_discard())
        self.assertEqual(self.app.text(), text)
        self.save_dialog.assert_not_called()

    def test_dirty_save_before_discard_must_finish_and_update_baseline(self):
        self.edit(self.app.text() + "\n")
        self.dialogs["askyesnocancel"].return_value = True
        self.assertFalse(self.app.confirm_discard(), "Canceling Save As must also cancel replacement")
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "case.json"
            self.save_dialog.return_value = str(destination)
            self.assertTrue(self.app.confirm_discard())
            self.assertEqual(parse_case(destination.read_text(encoding="utf-8")), parse_case(self.app.text()))
            self.assertEqual(self.app.saved_text, self.app.text())
            self.assertEqual(self.app.input_path.resolve(), destination.resolve())
            self.dialogs["askyesnocancel"].reset_mock()
            self.assertTrue(self.app.confirm_discard())
            self.dialogs["askyesnocancel"].assert_not_called()

    def test_invalid_dirty_data_cannot_be_saved_before_discard(self):
        self.edit("{invalid json}")
        self.dialogs["askyesnocancel"].return_value = True
        self.assertFalse(self.app.confirm_discard())
        self.assertNotEqual(self.app.saved_text, self.app.text())
        self.save_dialog.assert_not_called()

    def test_save_io_error_does_not_mark_dirty_document_saved(self):
        self.edit(self.app.text() + "\n")
        previous_baseline = self.app.saved_text
        previous_path = self.app.input_path
        self.save_dialog.return_value = "unwritable-case.json"
        self.dialogs["askyesnocancel"].return_value = True
        with patch("gui.Path.write_text", side_effect=PermissionError("Access denied")):
            self.assertFalse(self.app.confirm_discard())
        self.assertEqual(self.app.saved_text, previous_baseline)
        self.assertEqual(self.app.input_path, previous_path)
        self.assertNotEqual(self.app.saved_text, self.app.text())

    def test_export_cannot_overwrite_saved_input(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "case.json"
            self.save_dialog.return_value = str(destination)
            self.app.save_case()
            original = destination.read_bytes()
            self.calculate()
            self.app.export("json")
            self.assertEqual(destination.read_bytes(), original)

    def test_open_file_with_bom_and_cancel_replacement(self):
        current = self.app.text()
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "case.json"
            data = parse_case(current)
            data["name"] = "Lưới kiểm thử mở tệp"
            destination.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8-sig")
            self.open_dialog.return_value = str(destination)
            self.app.open_case()
            self.pump()
            self.assertEqual(parse_case(self.app.text()), data)
            self.assertEqual(self.app.saved_text, self.app.text())
            self.edit(self.app.text() + "\n")
            dirty = self.app.text()
            self.dialogs["askyesnocancel"].return_value = None
            self.app.load_example("luoi_9_nut.json")
            self.assertEqual(self.app.text(), dirty)

    def test_format_json_preserves_data_path_and_saved_baseline(self):
        data = parse_case(self.app.text())
        compact = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        path = Path("format-test.json")
        self.app.replace_editor(compact, path)
        self.pump()
        self.app.format_json()
        self.pump()
        self.assertEqual(parse_case(self.app.text()), data)
        self.assertGreater(self.app.text().count("\n"), 1)
        self.assertEqual(self.app.input_path, path)
        self.assertEqual(self.app.saved_text, compact)
        self.assertNotEqual(self.app.saved_text, self.app.text())

    def test_numeric_table_sorting_and_search(self):
        self.calculate()
        rows = self.app.table_rows["buses"]
        for row, amount, name in zip(rows, (10.0, 2.0, -1.0), ("Alpha", "Beta", "Gamma")):
            row["pg_mw"] = amount
            row["id"] = name
        self.app.render_table("buses")
        self.app.sort_table("buses", "pg_mw")
        tree = self.app.bus_table
        amounts = [float(tree.set(item, "pg_mw")) for item in tree.get_children()]
        self.assertEqual(amounts, [-1.0, 2.0, 10.0])
        self.app.sort_table("buses", "pg_mw")
        amounts = [float(tree.set(item, "pg_mw")) for item in tree.get_children()]
        self.assertEqual(amounts, [10.0, 2.0, -1.0])
        self.app.filter_vars["buses"].set("bEtA")
        self.app.render_table("buses")
        self.assertEqual([tree.set(item, "id") for item in tree.get_children()], ["Beta"])
        self.app.filter_vars["buses"].set("")
        self.app.render_table("buses")
        self.assertEqual(len(tree.get_children()), 3)


if __name__ == "__main__":
    unittest.main()
