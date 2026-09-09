"""Sơ đồ đơn tuyến (Single-Line Diagram / Network Topology) tương tác của lưới điện."""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, List, Optional, Tuple


class NetworkDiagram(ttk.Frame):
    """Trực quan hóa sơ đồ 1 sợi của lưới điện với các thanh cái, nguồn, phụ tải và đường dây."""

    def __init__(self, parent: tk.Widget, **kwargs):
        super().__init__(parent, **kwargs)
        self.result: Optional[Dict[str, Any]] = None
        self.theme_mode: str = "light"

        # Tọa độ các nút {bus_id: (x, y)}
        self.bus_coords: Dict[str, Tuple[float, float]] = {}
        self.bus_radii: Dict[str, float] = {}

        # Trạng thái kéo thả và pan
        self._dragging_bus: Optional[str] = None
        self._drag_offset_x: float = 0.0
        self._drag_offset_y: float = 0.0
        self._pan_start_x: float = 0.0
        self._pan_start_y: float = 0.0
        self._is_panning: bool = False

        # Tỉ lệ phóng to / thu nhỏ
        self.scale: float = 1.0
        self.offset_x: float = 0.0
        self.offset_y: float = 0.0

        # Hover tooltip
        self.hovered_item: Optional[str] = None

        self._build_ui()
        self._apply_theme_colors()

    def _build_ui(self):
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        # Thanh công cụ trên sơ đồ
        self.toolbar = ttk.Frame(self, padding=(10, 8))
        self.toolbar.grid(row=0, column=0, sticky="ew")

        self.title_label = ttk.Label(
            self.toolbar,
            text="SƠ ĐỒ ĐƠN TUYẾN LƯỚI ĐIỆN",
            font=("Segoe UI", 10, "bold")
        )
        self.title_label.pack(side="left", padx=(0, 15))

        self.info_label = ttk.Label(
            self.toolbar,
            text="Kéo thả nút để sắp xếp · Lăn chuột để phóng to/thu nhỏ",
            font=("Segoe UI", 9)
        )
        self.info_label.pack(side="left")

        # Nút điều khiển
        self.btn_reset = ttk.Button(self.toolbar, text="Bố cục mặc định", command=self.reset_layout, style="Small.TButton")
        self.btn_reset.pack(side="right", padx=(4, 0))

        self.btn_zoom_out = ttk.Button(self.toolbar, text="−", width=3, command=self._zoom_out, style="Small.TButton")
        self.btn_zoom_out.pack(side="right", padx=(2, 0))

        self.btn_zoom_in = ttk.Button(self.toolbar, text="+", width=3, command=self._zoom_in, style="Small.TButton")
        self.btn_zoom_in.pack(side="right", padx=(2, 0))

        self.show_labels_var = tk.BooleanVar(value=True)
        self.chk_labels = ttk.Checkbutton(
            self.toolbar,
            text="Hiện thông số P, Q",
            variable=self.show_labels_var,
            command=self.draw_diagram
        )
        self.chk_labels.pack(side="right", padx=(0, 10))

        # Canvas vẽ sơ đồ
        self.canvas = tk.Canvas(self, bg="#ffffff", bd=0, highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky="nsew")

        # Thanh chú giải (Legend) ở đáy
        self.legend_frame = ttk.Frame(self, padding=(10, 6))
        self.legend_frame.grid(row=2, column=0, sticky="ew")

        self.lbl_legend = ttk.Label(
            self.legend_frame,
            text="Chú giải:  ● Nút SLACK (Lam)  ● Nút PV (Lục)  ● Nút PQ (Xám)  ➜ Mũi tên: Chiều dòng công suất P  — Xanh: Tải <60%  — Vàng: 60-80%  — Đỏ: >80%",
            font=("Segoe UI", 9)
        )
        self.lbl_legend.pack(side="left")

        # Ràng buộc sự kiện Canvas
        self.canvas.bind("<ButtonPress-1>", self._on_canvas_press)
        self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.canvas.bind("<ButtonPress-2>", self._on_pan_start)
        self.canvas.bind("<ButtonPress-3>", self._on_pan_start)
        self.canvas.bind("<B2-Motion>", self._on_pan_drag)
        self.canvas.bind("<B3-Motion>", self._on_pan_drag)
        self.canvas.bind("<Motion>", self._on_canvas_motion)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Configure>", self._on_resize)

    def _apply_theme_colors(self):
        if self.theme_mode == "dark":
            self.bg_canvas = "#0f172a"
            self.bus_border = "#38bdf8"
            self.text_primary = "#f8fafc"
            self.text_muted = "#94a3b8"
            self.line_color = "#334155"
            self.card_bg = "#1e293b"
        else:
            self.bg_canvas = "#f8fafc"
            self.bus_border = "#0284c7"
            self.text_primary = "#0f172a"
            self.text_muted = "#64748b"
            self.line_color = "#cbd5e1"
            self.card_bg = "#ffffff"
        self.canvas.configure(bg=self.bg_canvas)

    def apply_theme(self, theme_mode: str):
        self.theme_mode = theme_mode
        self._apply_theme_colors()
        self.draw_diagram()

    def set_result(self, result: Optional[Dict[str, Any]]):
        self.result = result
        if result and result.get("buses"):
            self._compute_initial_layout()
        self.draw_diagram()

    def clear(self):
        self.result = None
        self.bus_coords.clear()
        self.canvas.delete("all")
        self._draw_empty_placeholder()

    def reset_layout(self):
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        if self.result and self.result.get("buses"):
            self._compute_initial_layout()
        self.draw_diagram()

    def _zoom_in(self):
        self.scale = min(2.5, self.scale * 1.2)
        self.draw_diagram()

    def _zoom_out(self):
        self.scale = max(0.4, self.scale / 1.2)
        self.draw_diagram()

    def _on_wheel(self, event):
        if event.delta > 0:
            self.scale = min(2.5, self.scale * 1.1)
        else:
            self.scale = max(0.4, self.scale / 1.1)
        self.draw_diagram()

    def _on_resize(self, _event):
        if not self.bus_coords and self.result and self.result.get("buses"):
            self._compute_initial_layout()
        self.draw_diagram()

    def _compute_initial_layout(self):
        if not self.result:
            return
        buses = self.result["buses"]
        n = len(buses)
        if n == 0:
            return

        w = max(400, self.canvas.winfo_width())
        h = max(300, self.canvas.winfo_height())
        cx, cy = w / 2, h / 2

        self.bus_coords.clear()

        if n == 2:
            self.bus_coords[str(buses[0]["id"])] = (cx - 160, cy)
            self.bus_coords[str(buses[1]["id"])] = (cx + 160, cy)
        elif n == 3:
            # Tam giác cân thanh thoát
            r = min(w, h) * 0.32
            self.bus_coords[str(buses[0]["id"])] = (cx, cy - r)
            self.bus_coords[str(buses[1]["id"])] = (cx - r * 1.05, cy + r * 0.7)
            self.bus_coords[str(buses[2]["id"])] = (cx + r * 1.05, cy + r * 0.7)
        elif n == 9:
            # Cấu hình chuẩn IEEE 9 bus: 3 generator buses (1, 2, 3) và 6 load/transfer buses
            r_gen = min(w, h) * 0.38
            r_inner = min(w, h) * 0.22
            angles_gen = [math.pi / 2, math.pi / 2 + 2 * math.pi / 3, math.pi / 2 + 4 * math.pi / 3]
            gen_buses = [str(buses[i]["id"]) for i in range(min(3, n))]
            for i, bus_id in enumerate(gen_buses):
                self.bus_coords[bus_id] = (cx + r_gen * math.cos(angles_gen[i] - math.pi / 2),
                                           cy - r_gen * math.sin(angles_gen[i] - math.pi / 2))
            other_buses = [str(b["id"]) for b in buses if str(b["id"]) not in gen_buses]
            for i, bus_id in enumerate(other_buses):
                ang = 2 * math.pi * i / len(other_buses)
                self.bus_coords[bus_id] = (cx + r_inner * math.cos(ang), cy + r_inner * math.sin(ang))
        else:
            # Bố trí vòng tròn đều cho các cấu hình khác
            r = min(w, h) * 0.35
            for i, bus in enumerate(buses):
                angle = -math.pi / 2 + 2 * math.pi * i / n
                self.bus_coords[str(bus["id"])] = (cx + r * math.cos(angle), cy + r * math.sin(angle))

    def _draw_empty_placeholder(self):
        w = self.canvas.winfo_width() or 600
        h = self.canvas.winfo_height() or 400
        self.canvas.create_text(
            w / 2, h / 2,
            text="Chưa có dữ liệu trào lưu công suất.\nBấm 'Tính toán trào lưu (F5)' để hiển thị sơ đồ 1 sợi.",
            font=("Segoe UI", 12),
            fill=self.text_muted,
            justify="center"
        )

    def draw_diagram(self):
        self.canvas.delete("all")
        if not self.result or not self.result.get("buses"):
            self._draw_empty_placeholder()
            return

        buses = self.result["buses"]
        branches = self.result["branches"]

        # Vẽ các nhánh (Branches / Lines / Transformers)
        for branch in branches:
            f_id, t_id = str(branch["from_bus"]), str(branch["to_bus"])
            if f_id in self.bus_coords and t_id in self.bus_coords:
                self._draw_branch(branch, self.bus_coords[f_id], self.bus_coords[t_id])

        # Vẽ các nút (Buses), máy phát và phụ tải
        for bus in buses:
            b_id = str(bus["id"])
            if b_id in self.bus_coords:
                self._draw_bus(bus, self.bus_coords[b_id])

    def _screen_pos(self, pt: Tuple[float, float]) -> Tuple[float, float]:
        cx = self.canvas.winfo_width() / 2
        cy = self.canvas.winfo_height() / 2
        x = cx + (pt[0] - cx + self.offset_x) * self.scale
        y = cy + (pt[1] - cy + self.offset_y) * self.scale
        return (x, y)

    def _draw_branch(self, branch: Dict[str, Any], pt1: Tuple[float, float], pt2: Tuple[float, float]):
        x1, y1 = self._screen_pos(pt1)
        x2, y2 = self._screen_pos(pt2)

        status = branch.get("status", True)
        loading = branch.get("loading_percent")

        # Xác định màu sắc đường dây dựa trên tỷ lệ tải
        if not status:
            color = "#94a3b8"  # Nhánh mở / cắt
            width = 1.5
            dash = (4, 4)
        elif loading is None:
            color = "#38bdf8" if self.theme_mode == "dark" else "#0284c7"
            width = 2.5
            dash = ()
        elif loading > 85.0:
            color = "#ef4444"  # Quá tải đỏ
            width = 3.5
            dash = ()
        elif loading >= 60.0:
            color = "#f59e0b"  # Tải cao vàng cam
            width = 3.0
            dash = ()
        else:
            color = "#10b981"  # Bình thường xanh lục
            width = 2.5
            dash = ()

        # Vẽ đường nối
        self.canvas.create_line(x1, y1, x2, y2, fill=color, width=width, dash=dash, tags=("branch", branch["id"]))

        # Mũi tên chỉ chiều dòng công suất tác dụng P
        p_from = branch.get("p_from_mw", 0.0)

        # Tính trung điểm
        mx = (x1 + x2) / 2
        my = (y1 + y2) / 2
        dx = x2 - x1
        dy = y2 - y1
        dist = math.hypot(dx, dy)
        if dist > 30 and status:
            ux, uy = dx / dist, dy / dist
            # Chiều dòng P: nếu p_from > 0 là từ 1 sang 2; nếu p_from < 0 là từ 2 sang 1
            if p_from >= 0:
                ax1 = mx - ux * 8
                ay1 = my - uy * 8
                ax2 = mx + ux * 8
                ay2 = my + uy * 8
            else:
                ax1 = mx + ux * 8
                ay1 = my + uy * 8
                ax2 = mx - ux * 8
                ay2 = my - uy * 8

            self.canvas.create_line(ax1, ay1, ax2, ay2, arrow=tk.LAST, arrowshape=(10, 12, 4),
                                    fill=color, width=2.5)

            # Hiển thị nhãn công suất nếu được bật
            if self.show_labels_var.get() and dist > 80:
                nx, ny = -uy * 14, ux * 14
                p_disp = abs(p_from)
                lbl_text = f"{branch['id']}: {p_disp:.1f} MW"
                if loading is not None:
                    lbl_text += f" ({loading:.0f}%)"
                self.canvas.create_text(
                    mx + nx, my + ny,
                    text=lbl_text,
                    font=("Segoe UI", 8, "bold"),
                    fill=color
                )

    def _draw_bus(self, bus: Dict[str, Any], pt: Tuple[float, float]):
        x, y = self._screen_pos(pt)
        b_type = bus.get("type_final", bus.get("type", "PQ"))
        b_id = str(bus["id"])

        # Màu sắc theo loại nút
        if b_type == "SLACK":
            bus_color = "#06b6d4"  # Cyan
        elif "PV" in b_type:
            bus_color = "#10b981"  # Emerald
        else:
            bus_color = "#64748b"  # Slate / Grey

        if "→" in b_type:
            bus_color = "#f59e0b"  # Chuyển loại nút (cam)

        # Vẽ thanh cái (Bus Bar) hình chữ nhật
        bw, bh = 54 * self.scale, 18 * self.scale
        rx1, ry1 = x - bw / 2, y - bh / 2
        rx2, ry2 = x + bw / 2, y + bh / 2

        self.canvas.create_rectangle(
            rx1, ry1, rx2, ry2,
            fill=bus_color,
            outline="#ffffff" if self.theme_mode == "dark" else "#0f172a",
            width=1.5,
            tags=("bus", b_id)
        )

        # Nhãn nút
        self.canvas.create_text(
            x, y,
            text=f"Nút {b_id}",
            font=("Segoe UI", max(7, int(9 * self.scale)), "bold"),
            fill="#ffffff"
        )

        # Thông số điện áp (U p.u. và kV) bên dưới thanh cái
        vm = bus.get("vm_pu", 1.0)
        deg = bus.get("va_deg", 0.0)
        v_kv = bus.get("voltage_kv")
        v_text = f"U: {vm:.3f} pu ({deg:+.1f}°)"
        if v_kv is not None:
            v_text += f"\n{v_kv:.1f} kV"

        self.canvas.create_text(
            x, y + bh / 2 + 14 * self.scale,
            text=v_text,
            font=("Segoe UI", max(7, int(8 * self.scale))),
            fill=self.text_primary,
            justify="center"
        )

        # Vẽ máy phát nếu Pg > 0 hoặc là nút SLACK / PV
        pg = bus.get("pg_mw", 0.0)
        if pg > 0.001 or b_type == "SLACK" or "PV" in b_type:
            gx = x
            gy = y - bh / 2 - 28 * self.scale
            gr = 12 * self.scale
            self.canvas.create_line(x, y - bh / 2, gx, gy + gr, fill=self.text_muted, width=1.5)
            self.canvas.create_oval(
                gx - gr, gy - gr, gx + gr, gy + gr,
                fill="#ecfdf5" if self.theme_mode == "light" else "#064e3b",
                outline="#10b981",
                width=1.5
            )
            self.canvas.create_text(gx, gy, text="~", font=("Segoe UI", max(8, int(11 * self.scale)), "bold"), fill="#10b981")
            if self.show_labels_var.get():
                qg = bus.get("qg_mvar", 0.0)
                self.canvas.create_text(
                    gx, gy - gr - 8 * self.scale,
                    text=f"Pg: {pg:.1f} MW\nQg: {qg:.1f} Mvar",
                    font=("Segoe UI", max(6, int(7.5 * self.scale))),
                    fill="#10b981",
                    justify="center"
                )

        # Vẽ phụ tải nếu Pd > 0
        pd = bus.get("pd_mw", 0.0)
        if pd > 0.001:
            lx = x
            ly1 = y + bh / 2
            ly2 = ly1 + 38 * self.scale
            self.canvas.create_line(
                lx, ly1, lx, ly2,
                arrow=tk.LAST,
                arrowshape=(8, 10, 4),
                fill="#ef4444" if self.theme_mode == "light" else "#f87171",
                width=2
            )
            if self.show_labels_var.get():
                qd = bus.get("qd_mvar", 0.0)
                self.canvas.create_text(
                    lx, ly2 + 12 * self.scale,
                    text=f"Pd: {pd:.1f} MW\nQd: {qd:.1f} Mvar",
                    font=("Segoe UI", max(6, int(7.5 * self.scale))),
                    fill="#ef4444" if self.theme_mode == "light" else "#f87171",
                    justify="center"
                )

    def _find_bus_at(self, event_x: float, event_y: float) -> Optional[str]:
        for b_id, pt in self.bus_coords.items():
            sx, sy = self._screen_pos(pt)
            bw = 60 * self.scale
            bh = 24 * self.scale
            if abs(event_x - sx) <= bw / 2 and abs(event_y - sy) <= bh / 2:
                return b_id
        return None

    def _on_canvas_press(self, event):
        bus_id = self._find_bus_at(event.x, event.y)
        if bus_id:
            self._dragging_bus = bus_id
            self._drag_offset_x = event.x
            self._drag_offset_y = event.y
            self.canvas.config(cursor="fleur")
        else:
            self._on_pan_start(event)

    def _on_canvas_drag(self, event):
        if self._dragging_bus:
            dx = (event.x - self._drag_offset_x) / self.scale
            dy = (event.y - self._drag_offset_y) / self.scale
            cur_x, cur_y = self.bus_coords[self._dragging_bus]
            self.bus_coords[self._dragging_bus] = (cur_x + dx, cur_y + dy)
            self._drag_offset_x = event.x
            self._drag_offset_y = event.y
            self.draw_diagram()
        elif self._is_panning:
            self._on_pan_drag(event)

    def _on_canvas_release(self, _event):
        self._dragging_bus = None
        self._is_panning = False
        self.canvas.config(cursor="")

    def _on_pan_start(self, event):
        self._is_panning = True
        self._pan_start_x = event.x
        self._pan_start_y = event.y
        self.canvas.config(cursor="hand2")

    def _on_pan_drag(self, event):
        if self._is_panning:
            dx = (event.x - self._pan_start_x) / self.scale
            dy = (event.y - self._pan_start_y) / self.scale
            self.offset_x += dx
            self.offset_y += dy
            self._pan_start_x = event.x
            self._pan_start_y = event.y
            self.draw_diagram()

    def _on_canvas_motion(self, event):
        bus_id = self._find_bus_at(event.x, event.y)
        if bus_id:
            self.canvas.config(cursor="hand2")
            if self.result:
                bus = next((b for b in self.result["buses"] if str(b["id"]) == bus_id), None)
                if bus:
                    info = f"Nút {bus_id} ({bus['type_final']}) · U={bus['vm_pu']:.4f} pu · Góc={bus['va_deg']:+.2f}° · Pg={bus['pg_mw']:.1f}MW · Pd={bus['pd_mw']:.1f}MW"
                    self.info_label.configure(text=info)
        else:
            if not self._dragging_bus and not self._is_panning:
                self.canvas.config(cursor="")
                self.info_label.configure(text="Kéo thả nút để sắp xếp · Lăn chuột để phóng to/thu nhỏ")
