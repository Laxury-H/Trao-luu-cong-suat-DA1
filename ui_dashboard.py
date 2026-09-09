"""Native Tk dashboard for verified power-flow results; no plotting dependencies."""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk


FONT = "Segoe UI"

THEMES = {
    "light": {
        "bg": "#f8fafc",
        "card": "#ffffff",
        "ink": "#0f172a",
        "muted": "#64748b",
        "teal": "#0d9488",
        "teal_soft": "#ccfbf1",
        "amber": "#d97706",
        "amber_soft": "#fef3c7",
        "red": "#dc2626",
        "border": "#e2e8f0",
        "chart_bg": "#ffffff",
        "safe_band": "#f0fdf4",
        "grid_line": "#e2e8f0",
    },
    "dark": {
        "bg": "#0f172a",
        "card": "#1e293b",
        "ink": "#f8fafc",
        "muted": "#94a3b8",
        "teal": "#2dd4bf",
        "teal_soft": "#134e4a",
        "amber": "#fbbf24",
        "amber_soft": "#78350f",
        "red": "#f87171",
        "border": "#334155",
        "chart_bg": "#1e293b",
        "safe_band": "#064e3b",
        "grid_line": "#334155",
    }
}


def _number(value, digits=3):
    if value is None:
        return "—"
    if abs(value) >= 1_000_000:
        return f"{value:.3e}"
    return f"{value:,.{digits}f}"


class Dashboard(ttk.Frame):
    """Scrollable summary, limits-aware voltage chart and Newton history."""

    def __init__(self, parent):
        super().__init__(parent, style="Dashboard.TFrame")
        self.result = None
        self.voltage_limits = {}
        self.theme_mode = "light"
        self._redraw_id = None
        self._width = 0
        self._card_columns = 0
        self._voltage_points = []
        self._history_points = []
        self._wrap_labels = []
        self._scroll_tag = f"DashboardWheel{id(self)}"
        self._configure_styles()

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.scroll_canvas = tk.Canvas(self, bg=THEMES["light"]["bg"], bd=0, highlightthickness=0,
                                       takefocus=True, yscrollincrement=24)
        self.scroll_canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.scroll_canvas.yview)
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.scroll_canvas.configure(yscrollcommand=self.scrollbar.set)
        self.content = ttk.Frame(self.scroll_canvas, padding=18, style="Dashboard.TFrame")
        self.content.columnconfigure(0, weight=1)
        self._content_window = self.scroll_canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.scroll_canvas.bind("<Configure>", self._resize)
        self.content.bind("<Configure>", self._content_resize)
        self.scroll_canvas.bind("<Prior>", lambda _e: self.scroll_canvas.yview_scroll(-1, "pages"))
        self.scroll_canvas.bind("<Next>", lambda _e: self.scroll_canvas.yview_scroll(1, "pages"))
        self.scroll_canvas.bind("<Home>", lambda _e: self.scroll_canvas.yview_moveto(0))
        self.scroll_canvas.bind("<End>", lambda _e: self.scroll_canvas.yview_moveto(1))

        self.heading = tk.StringVar()
        self.subtitle = tk.StringVar()
        heading_label = ttk.Label(self.content, textvariable=self.heading, style="Dashboard.Title.TLabel")
        heading_label.grid(row=0, column=0, sticky="ew")
        self._wrap_labels.append((heading_label, 0))
        subtitle_label = ttk.Label(self.content, textvariable=self.subtitle, style="Dashboard.Subtitle.TLabel")
        subtitle_label.grid(row=1, column=0, sticky="ew", pady=(5, 16))
        self._wrap_labels.append((subtitle_label, 0))

        self.empty = ttk.Frame(self.content, padding=26, style="Dashboard.Card.TFrame")
        self.empty.grid(row=2, column=0, sticky="ew")
        self.empty.columnconfigure(0, weight=1)
        self.empty_symbol = ttk.Label(self.empty, text="BẮT ĐẦU PHÂN TÍCH", style="Dashboard.Eyebrow.TLabel")
        self.empty_symbol.grid(row=0, column=0, sticky="w")
        self.empty_title = ttk.Label(self.empty, text="Sẵn sàng phân tích lưới điện", style="Dashboard.Section.TLabel")
        self.empty_title.grid(row=1, column=0, sticky="ew", pady=(16, 8))
        self.empty_message = ttk.Label(self.empty, style="Dashboard.Body.TLabel", justify="left")
        self.empty_message.grid(row=2, column=0, sticky="ew")
        self._wrap_labels.extend([(self.empty_title, 52), (self.empty_message, 52)])
        self.empty_steps = ttk.Label(
            self.empty, text="1   Chọn ví dụ hoặc mở tệp JSON\n\n2   Kiểm tra dữ liệu và tùy chọn giải\n\n3   Bấm Tính toán để xem kết quả",
            style="Dashboard.Body.TLabel", justify="left")
        self.empty_steps.grid(row=3, column=0, sticky="ew", pady=(24, 4))
        self._wrap_labels.append((self.empty_steps, 52))

        self.results_frame = ttk.Frame(self.content, style="Dashboard.TFrame")
        self.results_frame.grid(row=3, column=0, sticky="ew")
        self.results_frame.columnconfigure(0, weight=1)
        self.metrics = ttk.Frame(self.results_frame, style="Dashboard.TFrame")
        self.metrics.grid(row=0, column=0, sticky="ew")
        self.metric_values = {}
        self.metric_hints = {}
        self._cards = []

        KPI_SPECS = [
            ("generation", "TỔNG PHÁT · MW", "#10b981"),
            ("load", "PHỤ TẢI · MW", "#0284c7"),
            ("loss", "TỔN THẤT · MW", "#f43f5e"),
            ("loss_pct", "TỶ LỆ TỔN THẤT", "#f59e0b"),
            ("power_factor", "HỆ SỐ COS φ", "#8b5cf6"),
            ("iterations", "BƯỚC NEWTON", "#6366f1")
        ]

        for key, label, accent_color in KPI_SPECS:
            card = ttk.Frame(self.metrics, padding=(14, 12), style="Dashboard.Card.TFrame")
            card.columnconfigure(0, weight=1)
            header_row = ttk.Frame(card, style="Dashboard.Card.TFrame")
            header_row.grid(row=0, column=0, sticky="ew")

            # Colored mini accent dot
            dot = tk.Canvas(header_row, width=8, height=8, bg=THEMES["light"]["card"], bd=0, highlightthickness=0)
            dot.create_oval(1, 1, 7, 7, fill=accent_color, outline="")
            dot.pack(side="left", padx=(0, 6))
            setattr(card, "_accent_dot", dot)

            lbl = ttk.Label(header_row, text=label, style="Dashboard.Eyebrow.TLabel")
            lbl.pack(side="left")

            self.metric_values[key] = tk.StringVar(value="—")
            self.metric_hints[key] = tk.StringVar(value="")
            ttk.Label(card, textvariable=self.metric_values[key], style="Dashboard.Metric.TLabel").grid(
                row=1, column=0, sticky="w", pady=(6, 4))
            ttk.Label(card, textvariable=self.metric_hints[key], style="Dashboard.Hint.TLabel").grid(
                row=2, column=0, sticky="w")
            self._cards.append(card)

        self.alert_frame = ttk.Frame(self.results_frame, padding=(17, 15), style="Dashboard.Card.TFrame")
        self.alert_frame.grid(row=1, column=0, sticky="ew", pady=(4, 14))
        self.alert_frame.columnconfigure(0, weight=1)
        self.alert_title = ttk.Label(self.alert_frame, style="Dashboard.Section.TLabel")
        self.alert_title.grid(row=0, column=0, sticky="ew")
        self.alert_body = ttk.Frame(self.alert_frame, style="Dashboard.Card.TFrame")
        self.alert_body.grid(row=1, column=0, sticky="ew", pady=(7, 0))
        self.alert_body.columnconfigure(0, weight=1)
        self._warning_labels = []

        voltage_frame = self._panel(self.results_frame, 2, "Biểu đồ phân bố điện áp", "Dải xanh: Vùng chuẩn IEEE [0.95 – 1.05 p.u.] · Rê chuột để xem chi tiết")
        self.voltage_summary = voltage_frame.summary
        self.voltage_chart = tk.Canvas(voltage_frame, height=250, bg=THEMES["light"]["chart_bg"], bd=0, highlightthickness=0)
        self.voltage_chart.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.voltage_scrollbar = ttk.Scrollbar(voltage_frame, orient="horizontal", command=self.voltage_chart.xview)
        self.voltage_scrollbar.grid(row=3, column=0, sticky="ew")
        self.voltage_chart.configure(xscrollcommand=self.voltage_scrollbar.set)
        self.voltage_chart.bind("<Configure>", self._schedule_redraw)
        self.voltage_chart.bind("<Motion>", self._hover_voltage)
        self.voltage_chart.bind("<Leave>", lambda _e: self.voltage_detail.set(self._voltage_default_detail()))
        self.voltage_detail = tk.StringVar()
        detail = ttk.Label(voltage_frame, textvariable=self.voltage_detail, style="Dashboard.Hint.TLabel")
        detail.grid(row=4, column=0, sticky="ew", pady=(9, 0))
        self._wrap_labels.append((detail, 36))

        history_frame = self._panel(self.results_frame, 3, "Tiến trình hội tụ Newton–Raphson", "Sai lệch công suất lớn nhất qua từng bước giải")
        self.history_summary = history_frame.summary
        self.history_chart = tk.Canvas(history_frame, height=200, bg=THEMES["light"]["chart_bg"], bd=0, highlightthickness=0)
        self.history_chart.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.history_chart.bind("<Configure>", self._schedule_redraw)
        self.history_chart.bind("<Motion>", self._hover_history)
        self.history_chart.bind("<Leave>", lambda _e: self.history_detail.set(self._history_default_detail()))
        self.history_detail = tk.StringVar()
        history_detail_label = ttk.Label(history_frame, textvariable=self.history_detail, style="Dashboard.Hint.TLabel")
        history_detail_label.grid(row=3, column=0, sticky="ew", pady=(7, 0))
        self._wrap_labels.append((history_detail_label, 36))

        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind_class(self._scroll_tag, sequence, self._wheel)
        self._attach_scroll(self)
        self.bind("<Destroy>", self._destroyed, add="+")
        self.clear()

    def _configure_styles(self):
        theme = THEMES[self.theme_mode]
        style = ttk.Style(self)
        style.configure("Dashboard.TFrame", background=theme["bg"])
        style.configure("Dashboard.Card.TFrame", background=theme["card"])
        for name, bg, fg, font in (
            ("Title", theme["bg"], theme["ink"], (FONT, 19, "bold")),
            ("Subtitle", theme["bg"], theme["muted"], (FONT, 10)),
            ("Section", theme["card"], theme["ink"], (FONT, 12, "bold")),
            ("Body", theme["card"], theme["muted"], (FONT, 10)),
            ("Eyebrow", theme["card"], theme["muted"], (FONT, 8, "bold")),
            ("Metric", theme["card"], theme["ink"], (FONT, 21, "bold")),
            ("Hint", theme["card"], theme["muted"], (FONT, 9)),
            ("Warning", theme["card"], theme["amber"], (FONT, 10)),
        ):
            style.configure(f"Dashboard.{name}.TLabel", background=bg, foreground=fg, font=font)

    def apply_theme(self, theme_mode: str):
        self.theme_mode = theme_mode
        theme = THEMES[theme_mode]
        self._configure_styles()
        self.scroll_canvas.configure(bg=theme["bg"])
        self.voltage_chart.configure(bg=theme["chart_bg"])
        self.history_chart.configure(bg=theme["chart_bg"])
        for card in self._cards:
            dot = getattr(card, "_accent_dot", None)
            if dot:
                dot.configure(bg=theme["card"])
        self._schedule_redraw()

    def _panel(self, parent, row, title, subtitle):
        panel = ttk.Frame(parent, padding=(18, 16), style="Dashboard.Card.TFrame")
        panel.grid(row=row, column=0, sticky="ew", pady=(0, 14))
        panel.columnconfigure(0, weight=1)
        ttk.Label(panel, text=title, style="Dashboard.Section.TLabel").grid(row=0, column=0, sticky="w")
        panel.summary = tk.StringVar(value=subtitle)
        label = ttk.Label(panel, textvariable=panel.summary, style="Dashboard.Hint.TLabel")
        label.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self._wrap_labels.append((label, 36))
        return panel

    def clear(self, message="Kết quả sẽ xuất hiện ở đây sau khi giải thành công dữ liệu hiện tại."):
        self.result = None
        self.voltage_limits = {}
        self.heading.set("Tổng quan hệ thống")
        self.subtitle.set("Phân tích trào lưu công suất AC ba pha cân bằng")
        self.results_frame.grid_remove()
        self.empty.grid()
        theme = THEMES[self.theme_mode]
        self.empty_symbol.configure(text="BẮT ĐẦU PHÂN TÍCH", foreground=theme["teal"])
        self.empty_title.configure(text="Sẵn sàng phân tích lưới điện")
        self.empty_message.configure(text=message)
        self.empty_steps.grid()
        self.voltage_chart.delete("all")
        self.history_chart.delete("all")
        self._voltage_points = []
        self._history_points = []
        for variable in self.metric_values.values():
            variable.set("—")
        self.scroll_canvas.yview_moveto(0)

    def show_error(self, message):
        self.clear(str(message))
        theme = THEMES[self.theme_mode]
        self.empty_symbol.configure(text="CẦN KIỂM TRA", foreground=theme["red"])
        self.empty_title.configure(text="Chưa có kết quả hội tụ")
        self.empty_steps.grid_remove()
        self.subtitle.set("Kiểm tra thông báo bên dưới, điều chỉnh dữ liệu rồi tính lại.")

    def show_result(self, result, voltage_limits=None):
        if not result.get("converged"):
            self.show_error("Kết quả chưa được xác nhận hội tụ. Hãy kiểm tra dữ liệu và chạy lại.")
            return
        self.result = result
        self.voltage_limits = {str(key): tuple(value) for key, value in (voltage_limits or {}).items()}
        self.heading.set(str(result.get("name") or "Kết quả phân tích"))
        active = sum(bool(branch["status"]) for branch in result["branches"])
        self.subtitle.set(
            f"Đã hội tụ  ·  {len(result['buses'])} nút  ·  {active}/{len(result['branches'])} nhánh đóng"
            f"  ·  Cơ sở {result['base_mva']:g} MVA")
        summary = result["summary"]

        pg_tot = summary.get("pg_total_mw", 0.0)
        pd_tot = summary.get("pd_total_mw", 0.0)
        qd_tot = summary.get("qd_total_mvar", 0.0)
        p_loss = summary.get("p_total_loss_mw", 0.0)

        # Tính tỷ lệ tổn thất và cos phi
        loss_pct = (p_loss / pg_tot * 100.0) if pg_tot > 0 else 0.0
        s_load = math.hypot(pd_tot, qd_tot)
        cos_phi = (pd_tot / s_load) if s_load > 0 else 1.0

        self.metric_values["generation"].set(_number(pg_tot))
        self.metric_values["load"].set(_number(pd_tot))
        self.metric_values["loss"].set(_number(p_loss))
        self.metric_values["loss_pct"].set(f"{loss_pct:.2f} %")
        self.metric_values["power_factor"].set(f"{cos_phi:.3f}")
        self.metric_values["iterations"].set(str(result["iterations"]))

        self.metric_hints["generation"].set(f"Q  {_number(summary.get('qg_total_mvar', 0), 2)} Mvar")
        self.metric_hints["load"].set(f"Q  {_number(qd_tot, 2)} Mvar")
        self.metric_hints["loss"].set(f"ΔQ: {summary.get('q_net_mvar', 0):.2f} Mvar")
        self.metric_hints["loss_pct"].set(f"Tổn thất trên phát")
        self.metric_hints["power_factor"].set(f"S tải: {s_load:.1f} MVA")
        self.metric_hints["iterations"].set(f"{result.get('passes', 1)} lượt giải")

        self._show_warnings(result.get("warnings", []))
        buses = result["buses"]
        if buses:
            low, high = min(buses, key=lambda b: b["vm_pu"]), max(buses, key=lambda b: b["vm_pu"])
            self.voltage_summary.set(f"Thấp nhất: {low['vm_pu']:.4f} pu (Nút {low['id']}) · Cao nhất: {high['vm_pu']:.4f} pu (Nút {high['id']})")
        else:
            self.voltage_summary.set("Không có dữ liệu nút")
        self.voltage_detail.set(self._voltage_default_detail())
        self.history_summary.set(
            f"Sai lệch cuối {result['max_mismatch_pu']:.3e} p.u.  ·  Dung sai {result['tolerance_pu']:.1e} p.u.")
        self.history_detail.set(self._history_default_detail())
        self.empty.grid_remove()
        self.results_frame.grid()
        self.scroll_canvas.yview_moveto(0)
        self._reflow()
        self._schedule_redraw()

    def _show_warnings(self, warnings):
        for widget in self.alert_body.winfo_children():
            widget.destroy()
        self._warning_labels.clear()
        theme = THEMES[self.theme_mode]
        self.alert_title.configure(
            text=f"{len(warnings)} thông báo cần xem" if warnings else "Không có cảnh báo từ bộ giải",
            foreground=theme["amber"] if warnings else theme["teal"])
        messages = warnings or ["Không có cảnh báo điện áp, công suất hoặc chuyển loại nút trong kết quả này."]
        for index, message in enumerate(messages):
            label = ttk.Label(self.alert_body, text=("•  " if warnings else "") + str(message),
                              style="Dashboard.Warning.TLabel" if warnings else "Dashboard.Body.TLabel",
                              justify="left", wraplength=max(220, self._width - 70))
            label.grid(row=index, column=0, sticky="ew", pady=(3, 3))
            self._warning_labels.append(label)
            self._attach_scroll(label)

    def _limits(self, bus):
        limits = self.voltage_limits.get(str(bus["id"]))
        if limits is None and "vmin_pu" in bus and "vmax_pu" in bus:
            limits = (bus["vmin_pu"], bus["vmax_pu"])
        if limits and len(limits) == 2 and all(isinstance(value, (int, float)) and math.isfinite(value) for value in limits):
            return limits
        return None

    def _voltage_default_detail(self):
        if self.result and any(self._limits(bus) for bus in self.result["buses"]):
            return "Dải xanh nhạt: Vùng an toàn [0.95–1.05 p.u.] · Cột giới hạn nút · Rê chuột để xem chi tiết"
        return "Dải xanh nhạt: Vùng an toàn [0.95–1.05 p.u.] · Rê chuột để xem giá trị từng nút"

    def _history_default_detail(self):
        return "Thang log · Nét đứt: dung sai · Rê chuột để xem từng bước" + (
            " · Sai lệch 0 đặt ở đáy trục" if self.result and any(
                point["max_mismatch_pu"] == 0 for point in self.result.get("history", [])) else "")

    def _resize(self, event):
        self.scroll_canvas.itemconfigure(self._content_window, width=event.width)
        self._width = max(1, event.width - 36)
        self._reflow()

    def _content_resize(self, _event=None):
        self.scroll_canvas.configure(scrollregion=self.scroll_canvas.bbox("all"))

    def _reflow(self):
        # 6 cards: can be 6, 3, 2, or 1 column
        card_width = 160
        columns = 6 if self._width >= card_width * 6 + 40 else (
            3 if self._width >= card_width * 3 + 20 else (
                2 if self._width >= card_width * 2 + 12 else 1))
        if columns != self._card_columns:
            self._card_columns = columns
            for col in range(6):
                self.metrics.columnconfigure(col, weight=1 if col < columns else 0, uniform="kpi" if col < columns else "")
            for index, card in enumerate(self._cards):
                card.grid(row=index // columns, column=index % columns, sticky="nsew",
                          padx=(0 if index % columns == 0 else 5, 0 if index % columns == columns - 1 else 5), pady=(0, 10))
        for label, inset in self._wrap_labels:
            label.configure(wraplength=max(180, self._width - inset))
        for label in self._warning_labels:
            label.configure(wraplength=max(180, self._width - 34))
        self._schedule_redraw()

    def _schedule_redraw(self, _event=None):
        if self._redraw_id is None:
            self._redraw_id = self.after_idle(self._redraw)

    def _redraw(self):
        self._redraw_id = None
        if self.result is not None and self.winfo_exists():
            self._draw_voltage()
            self._draw_history()

    def _draw_voltage(self):
        canvas = self.voltage_chart
        canvas.delete("all")
        self._voltage_points.clear()
        buses = self.result["buses"]
        if not buses:
            return
        theme = THEMES[self.theme_mode]
        viewport = max(260, canvas.winfo_width())
        width = max(viewport, 80 + len(buses) * 76)
        canvas.configure(scrollregion=(0, 0, width, 250))
        if width > viewport:
            self.voltage_scrollbar.grid()
        else:
            self.voltage_scrollbar.grid_remove()
            canvas.xview_moveto(0)
        left, right, top, bottom = 55, width - 25, 24, 205
        values = [bus["vm_pu"] for bus in buses]
        values.extend([0.95, 1.05])
        for bus in buses:
            bounds = self._limits(bus)
            if bounds:
                values.extend(bounds)
        span = max(max(values) - min(values), 0.06)
        lower = min(values) - span * 0.15
        upper = max(values) + span * 0.15
        y = lambda value: bottom - (value - lower) / (upper - lower) * (bottom - top)

        # Draw safe operating band (0.95 - 1.05 p.u.)
        y_safe_lo = y(0.95)
        y_safe_hi = y(1.05)
        canvas.create_rectangle(left, y_safe_hi, right, y_safe_lo, fill=theme["safe_band"], outline="")

        # Nominal line 1.00 p.u.
        y_nom = y(1.0)
        canvas.create_line(left, y_nom, right, y_nom, fill="#38bdf8" if self.theme_mode == "dark" else "#0284c7", dash=(4, 4))
        canvas.create_text(right - 5, y_nom - 7, text="1.0 pu", fill=theme["muted"], anchor="e", font=(FONT, 7))

        for step in range(5):
            value = lower + (upper - lower) * step / 4
            yy = y(value)
            canvas.create_line(left, yy, right, yy, fill=theme["grid_line"])
            canvas.create_text(left - 9, yy, text=f"{value:.3f}", anchor="e", fill=theme["muted"], font=(FONT, 8))
        canvas.create_text(10, 8, text="p.u.", anchor="nw", fill=theme["muted"], font=(FONT, 8))

        gap = (right - left) / len(buses)
        line = []
        for index, bus in enumerate(buses):
            xx = left + gap * (index + 0.5)
            yy = y(bus["vm_pu"])
            line.extend((xx, yy))
            bounds = self._limits(bus)
            outside = bounds and (bus["vm_pu"] < bounds[0] - 1e-8 or bus["vm_pu"] > bounds[1] + 1e-8)
            color = theme["amber"] if outside else (theme["red"] if (bus["vm_pu"] < 0.90 or bus["vm_pu"] > 1.10) else theme["teal"])
            if bounds:
                lo_y, hi_y = y(bounds[0]), y(bounds[1])
                canvas.create_rectangle(xx - 12, hi_y, xx + 12, lo_y, fill=theme["teal_soft"], outline="")
                for limit_y in (lo_y, hi_y):
                    canvas.create_line(xx - 10, limit_y, xx + 10, limit_y, fill="#a9cfc2" if self.theme_mode == "light" else "#2dd4bf", width=2)
            label = str(bus["id"])
            short_label = label if len(label) <= 9 else label[:8] + "…"
            canvas.create_text(xx, bottom + 18, text=short_label, fill=theme["ink"], font=(FONT, 9, "bold"))
            self._voltage_points.append((xx, yy, bus, color))

        if len(line) > 2:
            canvas.create_line(*line, fill=theme["teal"], width=2.5)

        for xx, yy, bus, color in self._voltage_points:
            canvas.create_oval(xx - 5, yy - 5, xx + 5, yy + 5, fill=color, outline=theme["card"], width=2)
            canvas.create_text(xx, yy - 14, text=f"{bus['vm_pu']:.4f}", fill=color, font=(FONT, 8, "bold"))

    def _draw_history(self):
        canvas = self.history_chart
        canvas.delete("all")
        self._history_points.clear()
        history = self.result.get("history", [])
        theme = THEMES[self.theme_mode]
        width = max(260, canvas.winfo_width())
        if not history:
            canvas.create_text(width / 2, 85, text="Không có lịch sử bước giải", fill=theme["muted"], font=(FONT, 10))
            return
        left, right, top, bottom = 63, width - 18, 20, 162
        tolerance = self.result["tolerance_pu"]
        positives = [point["max_mismatch_pu"] for point in history if point["max_mismatch_pu"] > 0]
        positive_values = positives + ([tolerance] if tolerance > 0 else [])
        floor_log = math.log10(min(positive_values)) - 1 if positive_values else -16
        logs = [math.log10(point["max_mismatch_pu"]) if point["max_mismatch_pu"] > 0 else floor_log
                for point in history]
        tol_log = math.log10(tolerance) if tolerance > 0 else min(logs)
        low = math.floor(min(*logs, tol_log))
        high = math.ceil(max(*logs, tol_log))
        if low == high:
            high += 1
        y = lambda value: bottom - (value - low) / (high - low) * (bottom - top)
        count = min(4, high - low)
        ticks = sorted({round(low + (high - low) * step / count) for step in range(count + 1)})
        for value in ticks:
            yy = y(value)
            canvas.create_line(left, yy, right, yy, fill=theme["grid_line"])
            canvas.create_text(left - 9, yy, text=f"1e{value:+03d}", anchor="e", fill=theme["muted"], font=(FONT, 8))
        canvas.create_text(8, 2, text="Δmax (p.u.)", anchor="nw", fill=theme["muted"], font=(FONT, 8))
        tol_y = y(tol_log)
        canvas.create_line(left, tol_y, right, tol_y, fill=theme["amber"], dash=(5, 4), width=1.5)
        canvas.create_text(right - 5, tol_y - 8, text=f"Tol {tolerance:.1e}", fill=theme["amber"], anchor="e", font=(FONT, 7, "bold"))

        sequence = []
        previous_pass = None
        for index, (point, value) in enumerate(zip(history, logs)):
            xx = left + (right - left) * index / max(len(history) - 1, 1)
            if len(history) == 1:
                xx = (left + right) / 2
            yy = y(value)
            current_pass = point.get("pass", 1)
            if previous_pass is not None and current_pass != previous_pass:
                if len(sequence) > 2:
                    canvas.create_line(*sequence, fill=theme["teal"], width=2.5)
                sequence = []
                canvas.create_line(xx, top, xx, bottom, fill="#aebccd" if self.theme_mode == "light" else "#64748b", dash=(2, 4), width=1.5)
                canvas.create_text(xx + 4, top + 10, text=f"Lượt {current_pass}", fill=theme["muted"], anchor="w", font=(FONT, 8, "bold"))
            sequence.extend((xx, yy))
            self._history_points.append((xx, yy, point))
            previous_pass = current_pass
        if len(sequence) > 2:
            canvas.create_line(*sequence, fill=theme["teal"], width=2.5)
        for xx, yy, _point in self._history_points:
            canvas.create_oval(xx - 3.5, yy - 3.5, xx + 3.5, yy + 3.5, fill=theme["teal"], outline=theme["card"], width=1.5)
        max_labels = max(2, int((right - left) / 100))
        stride = max(1, math.ceil((len(history) - 1) / (max_labels - 1)))
        selected = list(range(0, len(history), stride))
        if selected[-1] != len(history) - 1:
            if len(selected) > 1 and len(history) - 1 - selected[-1] < stride * 0.6:
                selected.pop()
            selected.append(len(history) - 1)
        for index in selected:
            xx, _yy, point = self._history_points[index]
            canvas.create_text(xx, bottom + 20, text=f"L{point.get('pass', 1)}·B{point['iteration']}",
                               fill=theme["muted"], font=(FONT, 8))

    def _hover_voltage(self, event):
        if not self._voltage_points:
            return
        x = self.voltage_chart.canvasx(event.x)
        _x, _y, bus, _color = min(self._voltage_points, key=lambda point: abs(point[0] - x))
        limits = self._limits(bus)
        limit_text = f"Giới hạn {limits[0]:g}–{limits[1]:g} p.u." if limits else "Chưa có giới hạn"
        v_kv = bus.get("voltage_kv")
        kv_str = f" · {v_kv:.1f} kV" if v_kv is not None else ""
        self.voltage_detail.set(f"Nút {bus['id']} ({bus['type_final']}) · U = {bus['vm_pu']:.6f} pu{kv_str} · Góc = {bus.get('va_deg', 0.0):+.2f}° · {limit_text}")

    def _hover_history(self, event):
        if not self._history_points:
            return
        _x, _y, point = min(self._history_points, key=lambda row: abs(row[0] - event.x))
        self.history_detail.set(
            f"Lượt {point.get('pass', 1)} · Bước {point['iteration']} · Sai lệch max = {point['max_mismatch_pu']:.6e} p.u.")

    def _attach_scroll(self, widget):
        tags = widget.bindtags()
        if self._scroll_tag not in tags:
            widget.bindtags((*tags, self._scroll_tag))
        for child in widget.winfo_children():
            self._attach_scroll(child)

    def _wheel(self, event):
        if event.state & 0x0001 and event.widget == self.voltage_chart:
            amount = -1 if getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0 else 1
            self.voltage_chart.xview_scroll(amount, "units")
            return "break"
        bbox = self.scroll_canvas.bbox("all")
        if not bbox or bbox[3] <= self.scroll_canvas.winfo_height():
            return None
        if getattr(event, "num", None) in (4, 5):
            amount = -3 if event.num == 4 else 3
        else:
            delta = getattr(event, "delta", 0)
            amount = -int(delta / 120) * 3 if abs(delta) >= 120 else (-1 if delta > 0 else 1)
        self.scroll_canvas.yview_scroll(amount, "units")
        return "break"

    def _destroyed(self, event):
        if event.widget != self:
            return
        if self._redraw_id is not None:
            self.after_cancel(self._redraw_id)
            self._redraw_id = None
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.unbind_class(self._scroll_tag, sequence)
