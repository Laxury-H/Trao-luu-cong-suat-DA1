"""Sơ đồ đơn tuyến (Single-Line Diagram / Network Topology) tương tác của lưới điện.

Nâng cấp chuyên sâu hỗ trợ lưới nhiều nút (IEEE 14, 30, 39, 57, 118...):
- Thuật toán bố cục tự động Force-Directed (Spring-Embedder) chống chồng lấn.
- Bố cục vòng tròn đa tầng (Concentric Multi-Ring).
- Tự động căn chỉnh vừa vặn màn hình (Auto-Fit to View).
- Co giãn kích thước nút động (Adaptive Sizing) và bố trí nguồn/tải tỏa tròn (Radial Outward).
- Bộ lọc nhãn thông minh (LOD: Nhánh, Nguồn/Tải, Điện áp, Chỉ hiện cảnh báo).
- Thẻ thông tin chi tiết (Hover Tooltip Card) và chế độ tiêu điểm (Focus / Highlight Mode).
"""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, List, Optional, Set, Tuple


class NetworkDiagram(ttk.Frame):
    """Trực quan hóa sơ đồ 1 sợi của lưới điện với các thanh cái, nguồn, phụ tải và đường dây."""

    def __init__(self, parent: tk.Widget, **kwargs):
        super().__init__(parent, **kwargs)
        self.result: Optional[Dict[str, Any]] = None
        self.theme_mode: str = "light"

        # Tọa độ các nút trong không gian thế giới {bus_id: (x, y)}
        self.bus_coords: Dict[str, Tuple[float, float]] = {}

        # Trạng thái tương tác
        self._dragging_bus: Optional[str] = None
        self._drag_offset_x: float = 0.0
        self._drag_offset_y: float = 0.0
        self._pan_start_x: float = 0.0
        self._pan_start_y: float = 0.0
        self._is_panning: bool = False

        # Tỉ lệ phóng to / thu nhỏ và độ dời
        self.scale: float = 1.0
        self.offset_x: float = 0.0
        self.offset_y: float = 0.0

        # Chế độ chọn tiêu điểm (Highlight / Focus Mode)
        self.selected_bus: Optional[str] = None

        # Hover tooltip
        self.hover_bus: Optional[str] = None
        self.hover_branch: Optional[Dict[str, Any]] = None
        self.hover_pos: Optional[Tuple[float, float]] = None

        # Tùy chọn hiển thị
        self.show_branch_labels_var = tk.BooleanVar(value=True)
        self.show_gen_load_var = tk.BooleanVar(value=True)
        self.show_voltages_var = tk.BooleanVar(value=True)
        self.warnings_only_var = tk.BooleanVar(value=False)

        # Cấu hình màu sắc
        self._apply_theme_colors()
        self._build_ui()

    def _build_ui(self):
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        # 1. Thanh công cụ trên sơ đồ
        self.toolbar = ttk.Frame(self, padding=(8, 6))
        self.toolbar.grid(row=0, column=0, sticky="ew")

        # Cụm nút trái: Tiêu đề & Thông tin nút
        left_box = ttk.Frame(self.toolbar)
        left_box.pack(side="left", fill="x")

        self.title_label = ttk.Label(
            left_box,
            text="SƠ ĐỒ ĐƠN TUYẾN LƯỚI ĐIỆN",
            font=("Segoe UI", 10, "bold")
        )
        self.title_label.pack(side="left", padx=(0, 10))

        self.info_label = ttk.Label(
            left_box,
            text="Kéo thả nút để xếp · Nhấp nút để xem tiêu điểm · Cuộn chuột thu phóng",
            font=("Segoe UI", 9)
        )
        self.info_label.pack(side="left")

        # Cụm điều khiển phải
        right_box = ttk.Frame(self.toolbar)
        right_box.pack(side="right")

        # Nút Bố cục tự động
        self.btn_force = ttk.Button(
            right_box, text="✨ Bố cục tự động",
            command=self.apply_force_layout, style="Small.TButton"
        )
        self.btn_force.pack(side="left", padx=2)

        # Nút Đa tầng
        self.btn_concentric = ttk.Button(
            right_box, text="⭕ Đa tầng",
            command=self.apply_concentric_layout, style="Small.TButton"
        )
        self.btn_concentric.pack(side="left", padx=2)

        # Nút Vừa màn hình
        self.btn_fit = ttk.Button(
            right_box, text="⛶ Vừa khung",
            command=self.fit_to_view, style="Small.TButton"
        )
        self.btn_fit.pack(side="left", padx=2)

        # Nút Mặc định
        self.btn_reset = ttk.Button(
            right_box, text="Mặc định",
            command=self.reset_layout, style="Small.TButton"
        )
        self.btn_reset.pack(side="left", padx=2)

        # Thu phóng
        self.btn_zoom_out = ttk.Button(
            right_box, text="−", width=3,
            command=self._zoom_out, style="Small.TButton"
        )
        self.btn_zoom_out.pack(side="left", padx=1)

        self.btn_zoom_in = ttk.Button(
            right_box, text="+", width=3,
            command=self._zoom_in, style="Small.TButton"
        )
        self.btn_zoom_in.pack(side="left", padx=1)

        # 2. Thanh bộ lọc hiển thị (Filter Sub-bar)
        self.filter_bar = ttk.Frame(self, padding=(8, 3))
        self.filter_bar.grid(row=2, column=0, sticky="ew")

        ttk.Label(self.filter_bar, text="Bộ lọc:", font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0, 6))

        ttk.Checkbutton(
            self.filter_bar, text="Nhánh P/Q", variable=self.show_branch_labels_var,
            command=self.draw_diagram
        ).pack(side="left", padx=6)

        ttk.Checkbutton(
            self.filter_bar, text="Nguồn & Tải", variable=self.show_gen_load_var,
            command=self.draw_diagram
        ).pack(side="left", padx=6)

        ttk.Checkbutton(
            self.filter_bar, text="Điện áp", variable=self.show_voltages_var,
            command=self.draw_diagram
        ).pack(side="left", padx=6)

        ttk.Checkbutton(
            self.filter_bar, text="⚠️ Chỉ hiện cảnh báo", variable=self.warnings_only_var,
            command=self.draw_diagram
        ).pack(side="left", padx=6)

        self.btn_clear_focus = ttk.Button(
            self.filter_bar, text="Bỏ chọn tiêu điểm",
            command=self._clear_selection, style="Small.TButton"
        )
        # Sẽ pack khi có bus được chọn

        # 3. Canvas vẽ sơ đồ
        self.canvas = tk.Canvas(self, bg=self.bg_canvas, bd=0, highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky="nsew")

        # 4. Thanh chú giải (Legend) ở đáy
        self.legend_frame = ttk.Frame(self, padding=(8, 4))
        self.legend_frame.grid(row=3, column=0, sticky="ew")

        self.lbl_legend = ttk.Label(
            self.legend_frame,
            text="Chú giải:  ● Nút SLACK (Lam)  ● Nút PV (Lục)  ● Nút PQ (Xám)  ➜ Mũi tên: Chiều dòng P  — Xanh: Tải <60%  — Vàng: 60-80%  — Đỏ: >80%",
            font=("Segoe UI", 8)
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
        self.canvas.bind("<Leave>", self._on_leave)

    def _apply_theme_colors(self):
        if self.theme_mode == "dark":
            self.bg_canvas = "#0f172a"
            self.bus_border = "#38bdf8"
            self.text_primary = "#f8fafc"
            self.text_muted = "#94a3b8"
            self.line_color = "#334155"
            self.card_bg = "#1e293b"
            self.badge_bg = "#1e293b"
            self.badge_border = "#475569"
            self.tooltip_bg = "#020617"
            self.tooltip_fg = "#f8fafc"
            self.tooltip_border = "#38bdf8"
        else:
            self.bg_canvas = "#f8fafc"
            self.bus_border = "#0284c7"
            self.text_primary = "#0f172a"
            self.text_muted = "#64748b"
            self.line_color = "#cbd5e1"
            self.card_bg = "#ffffff"
            self.badge_bg = "#ffffff"
            self.badge_border = "#cbd5e1"
            self.tooltip_bg = "#0f172a"
            self.tooltip_fg = "#ffffff"
            self.tooltip_border = "#0284c7"

    def apply_theme(self, theme_mode: str):
        self.theme_mode = theme_mode
        self._apply_theme_colors()
        self.canvas.configure(bg=self.bg_canvas)
        self.draw_diagram()

    def set_result(self, result: Optional[Dict[str, Any]]):
        self.result = result
        self.selected_bus = None
        if self.btn_clear_focus.winfo_ismapped():
            self.btn_clear_focus.pack_forget()

        if result and result.get("buses"):
            self._compute_initial_layout()
        self.draw_diagram()

    def clear(self):
        self.result = None
        self.selected_bus = None
        self.bus_coords.clear()
        self.canvas.delete("all")
        self._draw_empty_placeholder()

    def reset_layout(self):
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.selected_bus = None
        if self.result and self.result.get("buses"):
            self._compute_initial_layout()
        self.draw_diagram()

    def _zoom_in(self):
        self.scale = min(3.5, self.scale * 1.2)
        self.draw_diagram()

    def _zoom_out(self):
        self.scale = max(0.25, self.scale / 1.2)
        self.draw_diagram()

    def _on_wheel(self, event):
        # Thu phóng tập trung tại vị trí con trỏ chuột
        factor = 1.15 if event.delta > 0 else (1.0 / 1.15)
        new_scale = max(0.25, min(3.5, self.scale * factor))
        if new_scale != self.scale:
            cx = self.canvas.winfo_width() / 2
            cy = self.canvas.winfo_height() / 2
            # Giữ điểm dưới chuột cố định
            self.scale = new_scale
            self.draw_diagram()

    def _on_resize(self, _event):
        if not self.bus_coords and self.result and self.result.get("buses"):
            self._compute_initial_layout()
            self.draw_diagram()

    def _compute_initial_layout(self):
        """Khởi tạo tọa độ cho mạng điện dựa trên quy mô."""
        if not self.result:
            return
        buses = self.result["buses"]
        n = len(buses)
        if n == 0:
            return

        w = max(500, self.canvas.winfo_width() or 700)
        h = max(400, self.canvas.winfo_height() or 500)
        cx, cy = w / 2, h / 2
        self.bus_coords.clear()

        if n == 2:
            self.bus_coords[str(buses[0]["id"])] = (cx - 160, cy)
            self.bus_coords[str(buses[1]["id"])] = (cx + 160, cy)
        elif n == 3:
            r = min(w, h) * 0.32
            self.bus_coords[str(buses[0]["id"])] = (cx, cy - r)
            self.bus_coords[str(buses[1]["id"])] = (cx - r * 1.05, cy + r * 0.7)
            self.bus_coords[str(buses[2]["id"])] = (cx + r * 1.05, cy + r * 0.7)
        elif n <= 9:
            # Vòng tròn vừa phải cho hệ thống nhỏ
            r = min(w, h) * 0.36
            for i, bus in enumerate(buses):
                angle = -math.pi / 2 + 2 * math.pi * i / n
                self.bus_coords[str(bus["id"])] = (cx + r * math.cos(angle), cy + r * math.sin(angle))
        else:
            # Với hệ thống từ 10 nút trở lên (như IEEE 14, 30...): tự động chạy Force-Directed Layout!
            self.apply_force_layout(silent=True)
            return

    def apply_force_layout(self, silent: bool = False):
        """Thuật toán lực đẩy Fruchterman-Reingold tối ưu hóa vị trí các nút trong đồ thị."""
        if not self.result or not self.result.get("buses"):
            return

        buses = self.result["buses"]
        branches = self.result.get("branches", [])
        nodes = [str(b["id"]) for b in buses]
        n = len(nodes)
        if n == 0:
            return

        w = max(600, self.canvas.winfo_width() or 800)
        h = max(450, self.canvas.winfo_height() or 600)
        cx, cy = w / 2, h / 2

        # Lấy tọa độ ban đầu (vòng tròn khởi tạo nếu chưa có)
        pos = {}
        init_r = min(w, h) * 0.38
        for i, node in enumerate(nodes):
            if node in self.bus_coords and not silent:
                pos[node] = list(self.bus_coords[node])
            else:
                ang = -math.pi / 2 + 2 * math.pi * i / n
                pos[node] = [cx + init_r * math.cos(ang), cy + init_r * math.sin(ang)]

        # Danh sách cạnh kết nối
        edges = []
        for br in branches:
            fb, tb = str(br.get("from_bus")), str(br.get("to_bus"))
            if fb in pos and tb in pos:
                edges.append((fb, tb))

        # Độ dài lò xo tự nhiên
        k = math.sqrt((w * h) / n) * 0.85
        temp = w / 8.0
        iterations = 90

        for _ in range(iterations):
            disp = {node: [0.0, 0.0] for node in nodes}

            # 1. Lực đẩy giữa mọi cặp nút (Coulomb repulsion)
            for i, u in enumerate(nodes):
                for v in nodes[i + 1:]:
                    dx = pos[u][0] - pos[v][0]
                    dy = pos[u][1] - pos[v][1]
                    dist = max(math.hypot(dx, dy), 1.0)
                    rep = (k * k) / dist
                    disp[u][0] += (dx / dist) * rep
                    disp[u][1] += (dy / dist) * rep
                    disp[v][0] -= (dx / dist) * rep
                    disp[v][1] -= (dy / dist) * rep

            # 2. Lực hút giữa các nút nối bằng nhánh (Hooke spring attraction)
            for u, v in edges:
                dx = pos[u][0] - pos[v][0]
                dy = pos[u][1] - pos[v][1]
                dist = max(math.hypot(dx, dy), 1.0)
                att = (dist * dist) / k
                disp[u][0] -= (dx / dist) * att
                disp[u][1] -= (dy / dist) * att
                disp[v][0] += (dx / dist) * att
                disp[v][1] += (dy / dist) * att

            # 3. Lực hấp dẫn nhẹ kéo về tâm để đồ thị không bị phân tán
            for node in nodes:
                dxc = pos[node][0] - cx
                dyc = pos[node][1] - cy
                dc = max(math.hypot(dxc, dyc), 1.0)
                disp[node][0] -= (dxc / dc) * (dc * 0.05)
                disp[node][1] -= (dyc / dc) * (dc * 0.05)

            # 4. Cập nhật vị trí với bước giảm dần (Simulated Annealing)
            for node in nodes:
                dlen = max(math.hypot(disp[node][0], disp[node][1]), 0.01)
                step = min(dlen, temp)
                pos[node][0] += (disp[node][0] / dlen) * step
                pos[node][1] += (disp[node][1] / dlen) * step

            temp *= 0.94

        self.bus_coords = {node: (pos[node][0], pos[node][1]) for node in nodes}
        self.fit_to_view()

    def apply_concentric_layout(self):
        """Bố trí các nút thành các vòng tròn đồng tâm cách đều (Generators ở ngoài, tải ở trong)."""
        if not self.result or not self.result.get("buses"):
            return

        buses = self.result["buses"]
        n = len(buses)
        if n == 0:
            return

        w = max(500, self.canvas.winfo_width() or 700)
        h = max(400, self.canvas.winfo_height() or 500)
        cx, cy = w / 2, h / 2

        # Phân loại nhóm nút: Nguồn (SLACK/PV) và Tải (PQ)
        gens = [b for b in buses if b.get("type_final", b.get("type")) in ("SLACK", "PV") or b.get("pg_mw", 0) > 0]
        loads = [b for b in buses if b not in gens]

        self.bus_coords.clear()

        if len(gens) > 0 and len(loads) > 0:
            # Vòng ngoài cho nguồn phát
            r_outer = min(w, h) * 0.42
            for i, b in enumerate(gens):
                ang = -math.pi / 2 + 2 * math.pi * i / len(gens)
                self.bus_coords[str(b["id"])] = (cx + r_outer * math.cos(ang), cy + r_outer * math.sin(ang))

            # Vòng trong cho tải (nếu nhiều tải thì chia 2 vòng tải)
            if len(loads) <= 12:
                r_inner = min(w, h) * 0.24
                for i, b in enumerate(loads):
                    ang = -math.pi / 2 + 2 * math.pi * i / len(loads)
                    self.bus_coords[str(b["id"])] = (cx + r_inner * math.cos(ang), cy + r_inner * math.sin(ang))
            else:
                half = len(loads) // 2
                r_mid = min(w, h) * 0.28
                r_core = min(w, h) * 0.16
                for i, b in enumerate(loads[:half]):
                    ang = -math.pi / 2 + 2 * math.pi * i / half
                    self.bus_coords[str(b["id"])] = (cx + r_mid * math.cos(ang), cy + r_mid * math.sin(ang))
                for i, b in enumerate(loads[half:]):
                    ang = -math.pi / 2 + 2 * math.pi * i / (len(loads) - half)
                    self.bus_coords[str(b["id"])] = (cx + r_core * math.cos(ang), cy + r_core * math.sin(ang))
        else:
            # Nếu toàn bộ là PQ: chia thành 2 vòng đồng tâm cách đều
            r1 = min(w, h) * 0.38
            r2 = min(w, h) * 0.22
            half = n // 2
            for i, b in enumerate(buses[:half]):
                ang = -math.pi / 2 + 2 * math.pi * i / half
                self.bus_coords[str(b["id"])] = (cx + r1 * math.cos(ang), cy + r1 * math.sin(ang))
            for i, b in enumerate(buses[half:]):
                ang = -math.pi / 2 + 2 * math.pi * i / (n - half)
                self.bus_coords[str(b["id"])] = (cx + r2 * math.cos(ang), cy + r2 * math.sin(ang))

        self.fit_to_view()

    def fit_to_view(self):
        """Tự động tính toán khung nhìn để toàn bộ sơ đồ lọt vừa vặn và cân đối trong màn hình."""
        if not self.bus_coords:
            self.draw_diagram()
            return

        w = self.canvas.winfo_width() or 700
        h = self.canvas.winfo_height() or 500

        xs = [pt[0] for pt in self.bus_coords.values()]
        ys = [pt[1] for pt in self.bus_coords.values()]

        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        span_x = max(max_x - min_x, 50.0)
        span_y = max(max_y - min_y, 50.0)

        # Lề an toàn
        margin = 85.0
        avail_w = max(100.0, w - 2 * margin)
        avail_h = max(100.0, h - 2 * margin)

        scale_x = avail_w / span_x
        scale_y = avail_h / span_y
        self.scale = max(0.35, min(scale_x, scale_y, 1.8))

        # Canh giữa
        mid_x = (min_x + max_x) / 2
        mid_y = (min_y + max_y) / 2
        self.offset_x = (w / 2) - mid_x
        self.offset_y = (h / 2) - mid_y

        self.draw_diagram()

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
        """Vẽ toàn bộ sơ đồ lưới điện lên canvas."""
        self.canvas.delete("all")
        if not self.result or not self.result.get("buses"):
            self._draw_empty_placeholder()
            return

        buses = self.result["buses"]
        branches = self.result["branches"]
        n_buses = len(buses)

        # Xác định kích thước thanh cái thích ứng
        if n_buses <= 9:
            bw, bh = 52, 18
        elif n_buses <= 20:
            bw, bh = 42, 15
        else:
            bw, bh = 36, 13
        self._current_bw = bw
        self._current_bh = bh

        # Danh sách nhánh nối với nút đang chọn (nếu có focus)
        connected_branch_ids: Set[str] = set()
        connected_bus_ids: Set[str] = set()
        if self.selected_bus:
            connected_bus_ids.add(self.selected_bus)
            for br in branches:
                fb = str(br.get("from_bus"))
                tb = str(br.get("to_bus"))
                if fb == self.selected_bus or tb == self.selected_bus:
                    connected_branch_ids.add(str(br["id"]))
                    connected_bus_ids.add(fb)
                    connected_bus_ids.add(tb)

        # 1. Vẽ các nhánh (Branches)
        for branch in branches:
            f_id, t_id = str(branch["from_bus"]), str(branch["to_bus"])
            if f_id in self.bus_coords and t_id in self.bus_coords:
                is_dimmed = False
                is_highlighted = False
                if self.selected_bus:
                    if str(branch["id"]) in connected_branch_ids:
                        is_highlighted = True
                    else:
                        is_dimmed = True
                self._draw_branch(branch, self.bus_coords[f_id], self.bus_coords[t_id],
                                  is_dimmed=is_dimmed, is_highlighted=is_highlighted)

        # 2. Vẽ các nút (Buses), máy phát và phụ tải
        for bus in buses:
            b_id = str(bus["id"])
            if b_id in self.bus_coords:
                is_dimmed = False
                is_selected = (b_id == self.selected_bus)
                if self.selected_bus and not is_selected and b_id not in connected_bus_ids:
                    is_dimmed = True
                self._draw_bus(bus, self.bus_coords[b_id], is_dimmed=is_dimmed, is_selected=is_selected)

        # 3. Vẽ Tooltip Card nếu đang hover
        self._draw_hover_tooltip()

    def _screen_pos(self, pt: Tuple[float, float]) -> Tuple[float, float]:
        cx = self.canvas.winfo_width() / 2
        cy = self.canvas.winfo_height() / 2
        x = cx + (pt[0] - cx + self.offset_x) * self.scale
        y = cy + (pt[1] - cy + self.offset_y) * self.scale
        return (x, y)

    def _draw_branch(self, branch: Dict[str, Any], pt1: Tuple[float, float], pt2: Tuple[float, float],
                     is_dimmed: bool = False, is_highlighted: bool = False):
        x1, y1 = self._screen_pos(pt1)
        x2, y2 = self._screen_pos(pt2)

        status = branch.get("status", True)
        loading = branch.get("loading_percent")

        if is_dimmed:
            color = "#334155" if self.theme_mode == "dark" else "#e2e8f0"
            width = 1.0
            dash = ()
        elif is_highlighted:
            color = "#f59e0b"  # Sáng màu hổ phách / vàng cam nổi bật
            width = 3.5
            dash = ()
        elif not status:
            color = "#94a3b8"
            width = 1.5
            dash = (4, 4)
        elif loading is None:
            color = "#38bdf8" if self.theme_mode == "dark" else "#0284c7"
            width = 2.0
            dash = ()
        elif loading > 85.0:
            color = "#ef4444"  # Quá tải đỏ
            width = 3.2
            dash = ()
        elif loading >= 60.0:
            color = "#f59e0b"  # Tải cao vàng
            width = 2.6
            dash = ()
        else:
            color = "#10b981"  # Xanh lục
            width = 2.0
            dash = ()

        # Đường nối
        self.canvas.create_line(x1, y1, x2, y2, fill=color, width=width, dash=dash,
                                tags=("branch", str(branch["id"])))

        if is_dimmed or not status:
            return

        # Mũi tên chỉ chiều dòng công suất tác dụng P
        p_from = branch.get("p_from_mw", 0.0)
        mx = (x1 + x2) / 2
        my = (y1 + y2) / 2
        dx = x2 - x1
        dy = y2 - y1
        dist = math.hypot(dx, dy)

        if dist > 35:
            ux, uy = dx / dist, dy / dist
            arrow_len = min(12.0, dist * 0.2)
            if p_from >= 0:
                ax1 = mx - ux * arrow_len
                ay1 = my - uy * arrow_len
                ax2 = mx + ux * arrow_len
                ay2 = my + uy * arrow_len
            else:
                ax1 = mx + ux * arrow_len
                ay1 = my + uy * arrow_len
                ax2 = mx - ux * arrow_len
                ay2 = my - uy * arrow_len

            self.canvas.create_line(ax1, ay1, ax2, ay2, arrow=tk.LAST,
                                    arrowshape=(8, 10, 3), fill=color, width=2.0)

            # Hiển thị nhãn công suất trên nhánh (Badge có nền che đường dây)
            should_show_label = self.show_branch_labels_var.get()
            if self.warnings_only_var.get():
                should_show_label = (loading is not None and loading >= 60.0)

            if should_show_label and dist > 65:
                nx, ny = -uy * 14, ux * 14
                p_disp = abs(p_from)
                lbl_text = f"{p_disp:.1f} MW"
                if loading is not None and loading > 0:
                    lbl_text += f" ({loading:.0f}%)"

                # Vẽ badge nền
                bx, by = mx + nx, my + ny
                f_size = max(7, int(8 * min(1.2, self.scale)))
                txt_font = ("Segoe UI", f_size, "bold")
                # Ước tính kích thước text để vẽ pill box
                tw = len(lbl_text) * (f_size * 0.62) + 8
                th = f_size + 6

                self.canvas.create_rectangle(
                    bx - tw / 2, by - th / 2, bx + tw / 2, by + th / 2,
                    fill=self.badge_bg, outline=color, width=1.0
                )
                self.canvas.create_text(
                    bx, by, text=lbl_text,
                    font=txt_font, fill=color
                )

    def _draw_bus(self, bus: Dict[str, Any], pt: Tuple[float, float],
                  is_dimmed: bool = False, is_selected: bool = False):
        x, y = self._screen_pos(pt)
        b_type = bus.get("type_final", bus.get("type", "PQ"))
        b_id = str(bus["id"])

        # Màu sắc theo loại nút
        if is_dimmed:
            bus_color = "#334155" if self.theme_mode == "dark" else "#cbd5e1"
            border_color = "#475569" if self.theme_mode == "dark" else "#94a3b8"
        else:
            if b_type == "SLACK":
                bus_color = "#06b6d4"  # Cyan
            elif "PV" in b_type:
                bus_color = "#10b981"  # Emerald
            else:
                bus_color = "#64748b"  # Slate / Grey

            if "→" in b_type:
                bus_color = "#f59e0b"  # Cam khi chuyển PV sang PQ

            border_color = "#ffffff" if self.theme_mode == "dark" else "#0f172a"

        bw = self._current_bw * self.scale
        bh = self._current_bh * self.scale
        rx1, ry1 = x - bw / 2, y - bh / 2
        rx2, ry2 = x + bw / 2, y + bh / 2

        # Nếu được chọn: vẽ vòng hào quang nổi bật (Glow)
        if is_selected:
            halo = 5 * self.scale
            self.canvas.create_rectangle(
                rx1 - halo, ry1 - halo, rx2 + halo, ry2 + halo,
                fill="", outline="#38bdf8", width=2.5
            )

        # Vẽ thanh cái
        self.canvas.create_rectangle(
            rx1, ry1, rx2, ry2,
            fill=bus_color,
            outline=border_color,
            width=1.5 if not is_selected else 2.0,
            tags=("bus", b_id)
        )

        # Nhãn mã nút
        font_bus = ("Segoe UI", max(7, int(8.5 * self.scale)), "bold")
        self.canvas.create_text(
            x, y,
            text=str(b_id),
            font=font_bus,
            fill="#ffffff" if not is_dimmed else "#94a3b8",
            tags=("bus", b_id)
        )

        if is_dimmed:
            return

        # Tính góc hướng tâm để đưa nguồn/tải tỏa tròn ra ngoài (Radial Outward)
        cx = self.canvas.winfo_width() / 2
        cy = self.canvas.winfo_height() / 2
        dx_c = x - cx
        dy_c = y - cy
        ang_out = math.atan2(dy_c, dx_c) if math.hypot(dx_c, dy_c) > 10 else -math.pi / 2

        # 1. Thông số điện áp (U p.u. và kV)
        vm = bus.get("vm_pu", 1.0)
        deg = bus.get("va_deg", 0.0)
        v_violation = (vm < 0.95 or vm > 1.05)

        should_show_v = self.show_voltages_var.get()
        if self.warnings_only_var.get():
            should_show_v = v_violation

        if should_show_v:
            v_text = f"{vm:.3f}"
            if not self.warnings_only_var.get():
                v_text += f" ({deg:+.1f}°)"

            v_color = "#ef4444" if v_violation else self.text_primary
            self.canvas.create_text(
                x, y + bh / 2 + 10 * self.scale,
                text=v_text,
                font=("Segoe UI", max(6, int(7.5 * self.scale)), "bold" if v_violation else "normal"),
                fill=v_color,
                justify="center"
            )

        # 2. Máy phát & Phụ tải
        if not self.show_gen_load_var.get() and not self.warnings_only_var.get():
            return

        pg = bus.get("pg_mw", 0.0)
        pd = bus.get("pd_mw", 0.0)
        has_gen = (pg > 0.001 or b_type in ("SLACK", "PV") or "PV" in b_type)
        has_load = (pd > 0.001)

        # Góc tỏa ra cho gen và load để không bao giờ đè nhau
        ang_gen = ang_out - 0.4 if (has_gen and has_load) else ang_out
        ang_load = ang_out + 0.4 if (has_gen and has_load) else ang_out

        dist_symbol = max(24 * self.scale, bh / 2 + 16 * self.scale)

        # Vẽ máy phát (Vòng tròn ~)
        if has_gen:
            gx = x + dist_symbol * math.cos(ang_gen)
            gy = y + dist_symbol * math.sin(ang_gen)
            gr = 9 * self.scale

            self.canvas.create_line(x, y, gx, gy, fill=self.text_muted, width=1.2)
            self.canvas.create_oval(
                gx - gr, gy - gr, gx + gr, gy + gr,
                fill="#ecfdf5" if self.theme_mode == "light" else "#064e3b",
                outline="#10b981", width=1.5
            )
            self.canvas.create_text(
                gx, gy, text="~",
                font=("Segoe UI", max(7, int(10 * self.scale)), "bold"),
                fill="#10b981"
            )

        # Vẽ phụ tải (Mũi tên chỉ ra ngoài)
        if has_load:
            lx1 = x + (bh / 2 + 2) * math.cos(ang_load)
            ly1 = y + (bh / 2 + 2) * math.sin(ang_load)
            lx2 = x + (dist_symbol + 14 * self.scale) * math.cos(ang_load)
            ly2 = y + (dist_symbol + 14 * self.scale) * math.sin(ang_load)

            self.canvas.create_line(
                lx1, ly1, lx2, ly2,
                arrow=tk.LAST, arrowshape=(7, 9, 3),
                fill="#ef4444" if self.theme_mode == "light" else "#f87171",
                width=1.8
            )

    def _draw_hover_tooltip(self):
        """Vẽ thẻ Tooltip nổi hiện đại khi người dùng rê chuột lên nút hoặc nhánh."""
        if not self.hover_pos:
            return

        mx, my = self.hover_pos
        card_w, card_h = 240, 130
        pad = 12

        # Điều chỉnh vị trí tooltip để không tràn màn hình
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        tx = mx + 16
        ty = my + 16
        if tx + card_w > cw - 10:
            tx = mx - card_w - 16
        if ty + card_h > ch - 10:
            ty = my - card_h - 16

        if self.hover_bus and self.result:
            bus = next((b for b in self.result["buses"] if str(b["id"]) == self.hover_bus), None)
            if not bus:
                return

            b_type = bus.get("type_final", bus.get("type", "PQ"))
            vm = bus.get("vm_pu", 1.0)
            deg = bus.get("va_deg", 0.0)
            v_kv = bus.get("voltage_kv")
            pg = bus.get("pg_mw", 0.0)
            qg = bus.get("qg_mvar", 0.0)
            pd = bus.get("pd_mw", 0.0)
            qd = bus.get("qd_mvar", 0.0)

            # Khung thẻ Tooltip
            self.canvas.create_rectangle(
                tx, ty, tx + card_w, ty + card_h,
                fill=self.tooltip_bg, outline=self.tooltip_border, width=1.5
            )
            # Tiêu đề nút
            self.canvas.create_text(
                tx + pad, ty + 18,
                text=f"🔷 NÚT {self.hover_bus} ({b_type})",
                font=("Segoe UI", 10, "bold"), fill=self.tooltip_fg, anchor="w"
            )
            # Nội dung thông số
            lines = [
                f"Điện áp: {vm:.4f} p.u.  ·  Góc: {deg:+.2f}°",
                f"Điện áp dây: {v_kv:.1f} kV" if v_kv else "Điện áp: Cơ sở chuẩn",
                f"Nguồn phát: {pg:.1f} MW  ·  {qg:.1f} Mvar",
                f"Phụ tải tiêu thụ: {pd:.1f} MW  ·  {qd:.1f} Mvar",
                "👉 Nhấp chuột để làm nổi bật kết nối"
            ]
            for idx, line in enumerate(lines):
                c = "#38bdf8" if idx == 4 else self.tooltip_fg
                f = ("Segoe UI", 8, "italic") if idx == 4 else ("Segoe UI", 8)
                self.canvas.create_text(
                    tx + pad, ty + 38 + idx * 17,
                    text=line, font=f, fill=c, anchor="w"
                )

        elif self.hover_branch:
            br = self.hover_branch
            fb = br.get("from_bus")
            tb = br.get("to_bus")
            pf = br.get("p_from_mw", 0.0)
            qf = br.get("q_from_mvar", 0.0)
            ploss = br.get("p_loss_mw", 0.0)
            loading = br.get("loading_percent")

            self.canvas.create_rectangle(
                tx, ty, tx + card_w, ty + card_h - 10,
                fill=self.tooltip_bg, outline=self.tooltip_border, width=1.5
            )
            self.canvas.create_text(
                tx + pad, ty + 18,
                text=f"⚡ NHÁNH {br.get('id')}: {fb} ➔ {tb}",
                font=("Segoe UI", 10, "bold"), fill=self.tooltip_fg, anchor="w"
            )
            lines = [
                f"Trào lưu P: {abs(pf):.2f} MW ({fb} ➔ {tb} if pf >= 0 else {tb} ➔ {fb})",
                f"Trào lưu Q: {qf:.2f} Mvar",
                f"Tổn thất đường dây: ΔP = {ploss:.3f} MW",
                f"Mức mang tải: {loading:.1f}%" if loading is not None else "Mức mang tải: Chưa có định mức"
            ]
            for idx, line in enumerate(lines):
                self.canvas.create_text(
                    tx + pad, ty + 38 + idx * 18,
                    text=line, font=("Segoe UI", 8), fill=self.tooltip_fg, anchor="w"
                )

    def _find_bus_at(self, event_x: float, event_y: float) -> Optional[str]:
        for b_id, pt in self.bus_coords.items():
            sx, sy = self._screen_pos(pt)
            bw = (self._current_bw + 10) * self.scale
            bh = (self._current_bh + 10) * self.scale
            if abs(event_x - sx) <= bw / 2 and abs(event_y - sy) <= bh / 2:
                return b_id
        return None

    def _find_branch_at(self, event_x: float, event_y: float) -> Optional[Dict[str, Any]]:
        if not self.result or not self.result.get("branches"):
            return None
        for br in self.result["branches"]:
            f_id, t_id = str(br.get("from_bus")), str(br.get("to_bus"))
            if f_id in self.bus_coords and t_id in self.bus_coords:
                x1, y1 = self._screen_pos(self.bus_coords[f_id])
                x2, y2 = self._screen_pos(self.bus_coords[t_id])
                # Khoảng cách từ điểm (event_x, event_y) đến đoạn thẳng (x1, y1)-(x2, y2)
                dx = x2 - x1
                dy = y2 - y1
                line_len_sq = dx * dx + dy * dy
                if line_len_sq > 0:
                    t = max(0.0, min(1.0, ((event_x - x1) * dx + (event_y - y1) * dy) / line_len_sq))
                    proj_x = x1 + t * dx
                    proj_y = y1 + t * dy
                    dist = math.hypot(event_x - proj_x, event_y - proj_y)
                    if dist <= 7.0:
                        return br
        return None

    def _on_canvas_press(self, event):
        bus_id = self._find_bus_at(event.x, event.y)
        if bus_id:
            # Chọn tiêu điểm bus
            if self.selected_bus == bus_id:
                self.selected_bus = None
                self.btn_clear_focus.pack_forget()
            else:
                self.selected_bus = bus_id
                self.btn_clear_focus.pack(side="left", padx=6)

            self._dragging_bus = bus_id
            self._drag_offset_x = event.x
            self._drag_offset_y = event.y
            self.canvas.config(cursor="fleur")
            self.draw_diagram()
        else:
            # Nhấp ngoài vùng trống: bỏ chọn tiêu điểm
            if self.selected_bus is not None:
                self.selected_bus = None
                self.btn_clear_focus.pack_forget()
                self.draw_diagram()
            self._on_pan_start(event)

    def _clear_selection(self):
        self.selected_bus = None
        self.btn_clear_focus.pack_forget()
        self.draw_diagram()

    def _on_canvas_drag(self, event):
        if self._dragging_bus:
            dx = (event.x - self._drag_offset_x) / self.scale
            dy = (event.y - self._drag_offset_y) / self.scale
            cur_x, cur_y = self.bus_coords[self._dragging_bus]
            self.bus_coords[self._dragging_bus] = (cur_x + dx, cur_y + dy)
            self._drag_offset_x = event.x
            self._drag_offset_y = event.y
            self.hover_pos = None
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
            self.hover_pos = None
            self.draw_diagram()

    def _on_canvas_motion(self, event):
        if self._dragging_bus or self._is_panning:
            return

        bus_id = self._find_bus_at(event.x, event.y)
        branch = self._find_branch_at(event.x, event.y) if not bus_id else None

        changed = False
        if bus_id != self.hover_bus:
            self.hover_bus = bus_id
            changed = True
        if branch != self.hover_branch:
            self.hover_branch = branch
            changed = True

        if bus_id or branch:
            self.hover_pos = (event.x, event.y)
            self.canvas.config(cursor="hand2")
            if bus_id and self.result:
                bus = next((b for b in self.result["buses"] if str(b["id"]) == bus_id), None)
                if bus:
                    self.info_label.configure(
                        text=f"Nút {bus_id} ({bus['type_final']}) · U={bus['vm_pu']:.4f} pu · Góc={bus['va_deg']:+.2f}° · Pg={bus['pg_mw']:.1f}MW · Pd={bus['pd_mw']:.1f}MW"
                    )
            elif branch:
                self.info_label.configure(
                    text=f"Nhánh {branch['id']} ({branch['from_bus']}➔{branch['to_bus']}) · P={abs(branch.get('p_from_mw', 0)):.1f}MW · ΔP={branch.get('p_loss_mw', 0):.3f}MW"
                )
            self.draw_diagram()
        else:
            if self.hover_pos is not None:
                self.hover_pos = None
                self.canvas.config(cursor="")
                if self.selected_bus:
                    self.info_label.configure(text=f"Đang xem tiêu điểm Nút {self.selected_bus} · Nhấp ra ngoài để bỏ chọn")
                else:
                    self.info_label.configure(text="Kéo thả nút để xếp · Nhấp nút để xem tiêu điểm · Cuộn chuột thu phóng")
                self.draw_diagram()

    def _on_leave(self, _event):
        if self.hover_pos is not None:
            self.hover_bus = None
            self.hover_branch = None
            self.hover_pos = None
            self.draw_diagram()
