"""Trình nhập liệu dạng bảng trực quan (Visual Table / Grid Input Editor) cho lưới điện.

Cho phép sinh viên và kỹ sư thêm, sửa, xóa các nút và nhánh trực tiếp trên
giao diện bảng tính dạng lưới giống PowerWorld / PSS/E hoặc dán trực tiếp từ Excel.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable, Dict, List, Optional


class BusDialog(tk.Toplevel):
    """Hộp thoại thêm hoặc sửa thông số nút."""

    def __init__(self, parent: tk.Widget, bus: Optional[Dict[str, Any]] = None, theme_mode: str = "light"):
        super().__init__(parent)
        self.title("Thông số nút" if bus else "Thêm nút mới")
        self.geometry("380x460")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.theme_mode = theme_mode
        self.result: Optional[Dict[str, Any]] = None
        bg = "#1e293b" if theme_mode == "dark" else "#f8fafc"
        fg = "#f8fafc" if theme_mode == "dark" else "#0f172a"
        self.configure(background=bg)

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)

        self.entries = {}
        fields = [
            ("id", "Mã nút (ID):", "1" if not bus else str(bus.get("id", ""))),
            ("type", "Loại nút:", "PQ" if not bus else str(bus.get("type", "PQ"))),
            ("vm_pu", "Điện áp U (p.u.):", "1.0" if not bus else str(bus.get("vm_pu", 1.0))),
            ("va_deg", "Góc điện áp (độ):", "0.0" if not bus else str(bus.get("va_deg", 0.0))),
            ("pd_mw", "Tải P (MW):", "0.0" if not bus else str(bus.get("pd_mw", 0.0))),
            ("qd_mvar", "Tải Q (Mvar):", "0.0" if not bus else str(bus.get("qd_mvar", 0.0))),
            ("pg_mw", "Phát P (MW):", "0.0" if not bus else str(bus.get("pg_mw", 0.0))),
            ("qg_mvar", "Phát Q (Mvar):", "0.0" if not bus else str(bus.get("qg_mvar", 0.0))),
            ("qmin_mvar", "Q phát tối thiểu (Mvar):", "" if not bus else str(bus.get("qmin_mvar") or "")),
            ("qmax_mvar", "Q phát tối đa (Mvar):", "" if not bus else str(bus.get("qmax_mvar") or "")),
        ]

        for idx, (key, label, default) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=idx, column=0, sticky="w", pady=3)
            if key == "type":
                cb = ttk.Combobox(frame, values=["PQ", "PV", "SLACK"], state="readonly", width=18)
                cb.set(default)
                cb.grid(row=idx, column=1, sticky="ew", pady=3, padx=(10, 0))
                self.entries[key] = cb
            else:
                entry = ttk.Entry(frame, width=20)
                entry.insert(0, default)
                entry.grid(row=idx, column=1, sticky="ew", pady=3, padx=(10, 0))
                self.entries[key] = entry

        btn_box = ttk.Frame(frame)
        btn_box.grid(row=len(fields), column=0, columnspan=2, sticky="e", pady=(18, 0))

        ttk.Button(btn_box, text="Hủy", command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(btn_box, text="Lưu", command=self._save, style="Primary.TButton").pack(side="right")

    def _save(self):
        bus_id = self.entries["id"].get().strip()
        if not bus_id:
            messagebox.showerror("Lỗi", "Mã nút không được để trống.", parent=self)
            return

        try:
            b_data = {
                "id": bus_id,
                "type": self.entries["type"].get(),
                "vm_pu": float(self.entries["vm_pu"].get()),
                "va_deg": float(self.entries["va_deg"].get()),
                "pd_mw": float(self.entries["pd_mw"].get()),
                "qd_mvar": float(self.entries["qd_mvar"].get()),
                "pg_mw": float(self.entries["pg_mw"].get()),
                "qg_mvar": float(self.entries["qg_mvar"].get()),
            }
            qmin_str = self.entries["qmin_mvar"].get().strip()
            if qmin_str:
                b_data["qmin_mvar"] = float(qmin_str)
            qmax_str = self.entries["qmax_mvar"].get().strip()
            if qmax_str:
                b_data["qmax_mvar"] = float(qmax_str)

            self.result = b_data
            self.destroy()
        except ValueError as exc:
            messagebox.showerror("Lỗi dữ liệu", f"Vui lòng nhập giá trị số hợp lệ: {exc}", parent=self)


class BranchDialog(tk.Toplevel):
    """Hộp thoại thêm hoặc sửa thông số nhánh / đường dây / máy biến áp."""

    def __init__(self, parent: tk.Widget, branch: Optional[Dict[str, Any]] = None, theme_mode: str = "light"):
        super().__init__(parent)
        self.title("Thông số nhánh" if branch else "Thêm nhánh mới")
        self.geometry("380x480")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.theme_mode = theme_mode
        self.result: Optional[Dict[str, Any]] = None
        bg = "#1e293b" if theme_mode == "dark" else "#f8fafc"
        self.configure(background=bg)

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)

        self.entries = {}
        fields = [
            ("id", "Mã nhánh (ID):", "L12" if not branch else str(branch.get("id", ""))),
            ("from_bus", "Nút đầu:", "1" if not branch else str(branch.get("from_bus", ""))),
            ("to_bus", "Nút cuối:", "2" if not branch else str(branch.get("to_bus", ""))),
            ("r_pu", "Điện trở R (p.u.):", "0.02" if not branch else str(branch.get("r_pu", 0.0))),
            ("x_pu", "Điện kháng X (p.u.):", "0.08" if not branch else str(branch.get("x_pu", 0.1))),
            ("b_pu", "Dung dẫn B (p.u.):", "0.0" if not branch else str(branch.get("b_pu", 0.0))),
            ("tap", "Tỷ số MBA (tap):", "1.0" if not branch else str(branch.get("tap", 1.0))),
            ("shift_deg", "Góc lệch pha (độ):", "0.0" if not branch else str(branch.get("shift_deg", 0.0))),
            ("rate_mva", "Định mức (MVA):", "" if not branch else str(branch.get("rate_mva") or "")),
            ("status", "Trạng thái:", "Đóng" if not branch or branch.get("status", True) else "Cắt"),
        ]

        for idx, (key, label, default) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=idx, column=0, sticky="w", pady=3)
            if key == "status":
                cb = ttk.Combobox(frame, values=["Đóng", "Cắt"], state="readonly", width=18)
                cb.set(default)
                cb.grid(row=idx, column=1, sticky="ew", pady=3, padx=(10, 0))
                self.entries[key] = cb
            else:
                entry = ttk.Entry(frame, width=20)
                entry.insert(0, default)
                entry.grid(row=idx, column=1, sticky="ew", pady=3, padx=(10, 0))
                self.entries[key] = entry

        btn_box = ttk.Frame(frame)
        btn_box.grid(row=len(fields), column=0, columnspan=2, sticky="e", pady=(18, 0))

        ttk.Button(btn_box, text="Hủy", command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(btn_box, text="Lưu", command=self._save, style="Primary.TButton").pack(side="right")

    def _save(self):
        br_id = self.entries["id"].get().strip()
        from_b = self.entries["from_bus"].get().strip()
        to_b = self.entries["to_bus"].get().strip()
        if not br_id or not from_b or not to_b:
            messagebox.showerror("Lỗi", "Mã nhánh, nút đầu và nút cuối không được để trống.", parent=self)
            return

        try:
            br_data = {
                "id": br_id,
                "from_bus": from_b,
                "to_bus": to_b,
                "r_pu": float(self.entries["r_pu"].get()),
                "x_pu": float(self.entries["x_pu"].get()),
                "b_pu": float(self.entries["b_pu"].get()),
                "tap": float(self.entries["tap"].get()),
                "shift_deg": float(self.entries["shift_deg"].get()),
                "status": (self.entries["status"].get() == "Đóng"),
            }
            rate_str = self.entries["rate_mva"].get().strip()
            if rate_str:
                br_data["rate_mva"] = float(rate_str)

            self.result = br_data
            self.destroy()
        except ValueError as exc:
            messagebox.showerror("Lỗi dữ liệu", f"Vui lòng nhập giá trị số hợp lệ: {exc}", parent=self)


class TableInputEditor(ttk.Frame):
    """Trình nhập liệu dạng bảng (Bảng Nút và Bảng Nhánh) với tương tác đầy đủ."""

    BUS_COLS = [
        ("id", "Nút", 55),
        ("type", "Loại", 70),
        ("vm_pu", "U (pu)", 75),
        ("va_deg", "Góc (°)", 75),
        ("pd_mw", "Pd (MW)", 80),
        ("qd_mvar", "Qd (Mvar)", 80),
        ("pg_mw", "Pg (MW)", 80),
        ("qg_mvar", "Qg (Mvar)", 80),
        ("qmin_mvar", "Qmin", 70),
        ("qmax_mvar", "Qmax", 70),
    ]

    BRANCH_COLS = [
        ("id", "Mã", 75),
        ("from_bus", "Đầu", 55),
        ("to_bus", "Cuối", 55),
        ("r_pu", "R (pu)", 75),
        ("x_pu", "X (pu)", 75),
        ("b_pu", "B (pu)", 75),
        ("tap", "K (tap)", 70),
        ("shift_deg", "Góc lệch", 75),
        ("status", "Đóng", 65),
    ]

    def __init__(self, parent: tk.Widget, on_change: Optional[Callable[[], None]] = None, **kwargs):
        super().__init__(parent, **kwargs)
        self.on_change = on_change
        self.theme_mode = "light"
        self.case_name = "Lưới điện"
        self.base_mva = 100.0

        self.buses_data: List[Dict[str, Any]] = []
        self.branches_data: List[Dict[str, Any]] = []

        self._build_ui()

    def _build_ui(self):
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        paned = ttk.Panedwindow(self, orient="vertical")
        paned.grid(row=0, column=0, sticky="nsew")

        # Khung Bảng Nút (Trên)
        frame_bus = ttk.Frame(paned, style="Card.TFrame", padding=10)
        paned.add(frame_bus, weight=1)
        self._build_bus_section(frame_bus)

        # Khung Bảng Nhánh (Dưới)
        frame_br = ttk.Frame(paned, style="Card.TFrame", padding=10)
        paned.add(frame_br, weight=1)
        self._build_branch_section(frame_br)

    def _build_bus_section(self, parent: ttk.Frame):
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)

        tb = ttk.Frame(parent, style="Card.TFrame")
        tb.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        ttk.Label(tb, text="BẢNG NÚT", font=("Segoe UI", 10, "bold")).pack(side="left")
        self.lbl_bus_count = ttk.Label(tb, text="(0 nút)", style="CardMuted.TLabel")
        self.lbl_bus_count.pack(side="left", padx=(6, 0))

        ttk.Button(tb, text="➕ Thêm", command=self._add_bus, style="Small.TButton").pack(side="right", padx=(3, 0))
        ttk.Button(tb, text="✏️ Sửa", command=self._edit_bus, style="Small.TButton").pack(side="right", padx=(3, 0))
        ttk.Button(tb, text="🗑️ Xóa", command=self._delete_bus, style="Small.TButton").pack(side="right", padx=(3, 0))
        ttk.Button(tb, text="📋 Dán Excel", command=self._paste_buses_from_clipboard, style="Small.TButton").pack(side="right", padx=(3, 6))

        tree_frame = ttk.Frame(parent)
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        self.bus_tree = ttk.Treeview(tree_frame, columns=[col[0] for col in self.BUS_COLS], show="headings", selectmode="extended")
        for key, title, width in self.BUS_COLS:
            self.bus_tree.heading(key, text=title)
            self.bus_tree.column(key, width=width, minwidth=50, anchor="w" if key in ("id", "type") else "e")

        xbar = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.bus_tree.xview)
        ybar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.bus_tree.yview)
        self.bus_tree.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)

        self.bus_tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")

        self.bus_tree.bind("<Double-1>", lambda _e: self._edit_bus())

    def _build_branch_section(self, parent: ttk.Frame):
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)

        tb = ttk.Frame(parent, style="Card.TFrame")
        tb.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        ttk.Label(tb, text="BẢNG NHÁNH / ĐƯỜNG DÂY", font=("Segoe UI", 10, "bold")).pack(side="left")
        self.lbl_branch_count = ttk.Label(tb, text="(0 nhánh)", style="CardMuted.TLabel")
        self.lbl_branch_count.pack(side="left", padx=(6, 0))

        ttk.Button(tb, text="➕ Thêm", command=self._add_branch, style="Small.TButton").pack(side="right", padx=(3, 0))
        ttk.Button(tb, text="✏️ Sửa", command=self._edit_branch, style="Small.TButton").pack(side="right", padx=(3, 0))
        ttk.Button(tb, text="🗑️ Xóa", command=self._delete_branch, style="Small.TButton").pack(side="right", padx=(3, 0))
        ttk.Button(tb, text="📋 Dán Excel", command=self._paste_branches_from_clipboard, style="Small.TButton").pack(side="right", padx=(3, 6))

        tree_frame = ttk.Frame(parent)
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        self.branch_tree = ttk.Treeview(tree_frame, columns=[col[0] for col in self.BRANCH_COLS], show="headings", selectmode="extended")
        for key, title, width in self.BRANCH_COLS:
            self.branch_tree.heading(key, text=title)
            self.branch_tree.column(key, width=width, minwidth=50, anchor="w" if key in ("id", "from_bus", "to_bus") else "e")

        xbar = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.branch_tree.xview)
        ybar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.branch_tree.yview)
        self.branch_tree.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)

        self.branch_tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")

        self.branch_tree.bind("<Double-1>", lambda _e: self._edit_branch())

    def apply_theme(self, theme_mode: str):
        self.theme_mode = theme_mode

    def set_case_data(self, case: Dict[str, Any]):
        """Nạp dữ liệu từ case dict vào các bảng."""
        self.case_name = case.get("name", "Lưới điện")
        self.base_mva = float(case.get("base_mva", 100.0))
        self.buses_data = [dict(b) for b in case.get("buses", [])]
        self.branches_data = [dict(b) for b in case.get("branches", [])]
        self.render_all()

    def get_case_data(self) -> Dict[str, Any]:
        """Lấy dữ liệu lưới điện hiện tại từ các bảng."""
        return {
            "name": self.case_name,
            "base_mva": self.base_mva,
            "buses": [dict(b) for b in self.buses_data],
            "branches": [dict(b) for b in self.branches_data]
        }

    def render_all(self):
        self.render_buses()
        self.render_branches()

    def render_buses(self):
        self.bus_tree.delete(*self.bus_tree.get_children())
        for idx, bus in enumerate(self.buses_data):
            vals = []
            for col, _, _ in self.BUS_COLS:
                val = bus.get(col)
                if val is None or val == "":
                    vals.append("—")
                elif isinstance(val, float):
                    vals.append(f"{val:.4f}" if col in ("vm_pu", "va_deg") else f"{val:.2f}")
                else:
                    vals.append(str(val))
            tag = "even" if idx % 2 == 0 else "odd"
            self.bus_tree.insert("", "end", iid=str(idx), values=vals, tags=(tag,))
        self.lbl_bus_count.configure(text=f"({len(self.buses_data)} nút)")

    def render_branches(self):
        self.branch_tree.delete(*self.branch_tree.get_children())
        for idx, br in enumerate(self.branches_data):
            vals = []
            for col, _, _ in self.BRANCH_COLS:
                val = br.get(col)
                if val is None or val == "":
                    vals.append("—")
                elif col == "status":
                    vals.append("Đóng" if val else "Cắt")
                elif isinstance(val, float):
                    vals.append(f"{val:.4f}" if col in ("r_pu", "x_pu", "b_pu") else f"{val:.2f}")
                else:
                    vals.append(str(val))
            tag = "even" if idx % 2 == 0 else "odd"
            self.branch_tree.insert("", "end", iid=str(idx), values=vals, tags=(tag,))
        self.lbl_branch_count.configure(text=f"({len(self.branches_data)} nhánh)")

    def _notify_change(self):
        if self.on_change:
            self.on_change()

    # Thao tác Nút
    def _add_bus(self):
        dlg = BusDialog(self, theme_mode=self.theme_mode)
        self.wait_window(dlg)
        if dlg.result:
            self.buses_data.append(dlg.result)
            self.render_buses()
            self._notify_change()

    def _edit_bus(self):
        selected = self.bus_tree.selection()
        if not selected:
            return
        idx = int(selected[0])
        dlg = BusDialog(self, bus=self.buses_data[idx], theme_mode=self.theme_mode)
        self.wait_window(dlg)
        if dlg.result:
            self.buses_data[idx] = dlg.result
            self.render_buses()
            self._notify_change()

    def _delete_bus(self):
        selected = self.bus_tree.selection()
        if not selected:
            return
        indices = sorted([int(s) for s in selected], reverse=True)
        for idx in indices:
            del self.buses_data[idx]
        self.render_buses()
        self._notify_change()

    # Thao tác Nhánh
    def _add_branch(self):
        dlg = BranchDialog(self, theme_mode=self.theme_mode)
        self.wait_window(dlg)
        if dlg.result:
            self.branches_data.append(dlg.result)
            self.render_branches()
            self._notify_change()

    def _edit_branch(self):
        selected = self.branch_tree.selection()
        if not selected:
            return
        idx = int(selected[0])
        dlg = BranchDialog(self, branch=self.branches_data[idx], theme_mode=self.theme_mode)
        self.wait_window(dlg)
        if dlg.result:
            self.branches_data[idx] = dlg.result
            self.render_branches()
            self._notify_change()

    def _delete_branch(self):
        selected = self.branch_tree.selection()
        if not selected:
            return
        indices = sorted([int(s) for s in selected], reverse=True)
        for idx in indices:
            del self.branches_data[idx]
        self.render_branches()
        self._notify_change()

    # Dán từ Clipboard
    def _paste_buses_from_clipboard(self):
        try:
            raw = self.clipboard_get()
        except tk.TclError:
            messagebox.showinfo("Dán", "Không có dữ liệu văn bản trong bộ nhớ tạm.", parent=self)
            return

        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        added = 0
        for line in lines:
            parts = line.split("\t") if "\t" in line else line.split(",")
            if len(parts) >= 2:
                b_id = parts[0].strip()
                if not b_id or b_id.lower() in ("id", "nut", "mã nút"):
                    continue
                raw_type = parts[1].strip().upper()
                b_type = "SLACK" if "SLACK" in raw_type or raw_type == "1" else ("PV" if "PV" in raw_type or raw_type == "2" else "PQ")
                try:
                    bus = {
                        "id": b_id,
                        "type": b_type,
                        "vm_pu": float(parts[2].replace(",", ".")) if len(parts) > 2 and parts[2].strip() else 1.0,
                        "va_deg": float(parts[3].replace(",", ".")) if len(parts) > 3 and parts[3].strip() else 0.0,
                        "pd_mw": float(parts[4].replace(",", ".")) if len(parts) > 4 and parts[4].strip() else 0.0,
                        "qd_mvar": float(parts[5].replace(",", ".")) if len(parts) > 5 and parts[5].strip() else 0.0,
                        "pg_mw": float(parts[6].replace(",", ".")) if len(parts) > 6 and parts[6].strip() else 0.0,
                        "qg_mvar": float(parts[7].replace(",", ".")) if len(parts) > 7 and parts[7].strip() else 0.0,
                    }
                    self.buses_data.append(bus)
                    added += 1
                except ValueError:
                    continue

        if added > 0:
            self.render_buses()
            self._notify_change()
            messagebox.showinfo("Thành công", f"Đã nạp {added} nút từ clipboard!", parent=self)
        else:
            messagebox.showwarning("Không đọc được", "Không tìm thấy dữ liệu nút hợp lệ từ clipboard.", parent=self)

    def _paste_branches_from_clipboard(self):
        try:
            raw = self.clipboard_get()
        except tk.TclError:
            messagebox.showinfo("Dán", "Không có dữ liệu văn bản trong bộ nhớ tạm.", parent=self)
            return

        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        added = 0
        for line in lines:
            parts = line.split("\t") if "\t" in line else line.split(",")
            if len(parts) >= 3:
                f_b = parts[1].strip() if len(parts) >= 4 else parts[0].strip()
                t_b = parts[2].strip() if len(parts) >= 4 else parts[1].strip()
                br_id = parts[0].strip() if len(parts) >= 4 else f"L{f_b}_{t_b}"
                if f_b.lower() in ("from", "nut_dau", "đầu") or t_b.lower() in ("to", "nut_cuoi", "cuối"):
                    continue
                try:
                    r_idx = 3 if len(parts) >= 4 else 2
                    x_idx = 4 if len(parts) >= 5 else 3
                    b_idx = 5 if len(parts) >= 6 else 4
                    tap_idx = 6 if len(parts) >= 7 else 5

                    br = {
                        "id": br_id,
                        "from_bus": f_b,
                        "to_bus": t_b,
                        "r_pu": float(parts[r_idx].replace(",", ".")) if len(parts) > r_idx and parts[r_idx].strip() else 0.0,
                        "x_pu": float(parts[x_idx].replace(",", ".")) if len(parts) > x_idx and parts[x_idx].strip() else 0.1,
                        "b_pu": float(parts[b_idx].replace(",", ".")) if len(parts) > b_idx and parts[b_idx].strip() else 0.0,
                        "tap": float(parts[tap_idx].replace(",", ".")) if len(parts) > tap_idx and parts[tap_idx].strip() else 1.0,
                        "shift_deg": 0.0,
                        "status": True,
                    }
                    self.branches_data.append(br)
                    added += 1
                except ValueError:
                    continue

        if added > 0:
            self.render_branches()
            self._notify_change()
            messagebox.showinfo("Thành công", f"Đã nạp {added} nhánh từ clipboard!", parent=self)
        else:
            messagebox.showwarning("Không đọc được", "Không tìm thấy dữ liệu nhánh hợp lệ từ clipboard.", parent=self)
