"""Giao diện máy tính để bàn: python gui.py."""
from __future__ import annotations

import copy
import csv
import json
import math
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from contingency import run_n1_contingency_analysis
from data_io import (
    create_sample_excel_template,
    export_case_to_excel,
    export_full_results_to_excel,
    load_from_csv,
    load_from_excel,
)
from powerflow import CaseError, format_report, parse_case, solve_power_flow, validate_case
from solvers import SOLVER_DESCRIPTIONS, benchmark_all_solvers
from ui_dashboard import Dashboard
from ui_editor import JsonEditor
from ui_table_editor import TableInputEditor
from ui_topology import NetworkDiagram

ROOT = Path(__file__).resolve().parent

SOLVER_METHODS = [
    ("Newton–Raphson (Chuẩn CN)", "NR"),
    ("Phân tách nhanh (FDPF)", "FDPF"),
    ("Gauss–Seidel (Lặp điện áp)", "GS"),
    ("Trào lưu một chiều (DC Flow)", "DC"),
]

THEMES = {
    "light": {
        "bg": "#f8fafc",
        "surface": "#ffffff",
        "ink": "#0f172a",
        "muted": "#64748b",
        "teal": "#0d9488",
        "teal_hover": "#0f766e",
        "teal_pressed": "#115e59",
        "line": "#e2e8f0",
        "red": "#dc2626",
        "header_bg": "#0f172a",
        "header_fg": "#f8fafc",
        "header_sub": "#94a3b8",
        "tree_bg": "#ffffff",
        "tree_fg": "#0f172a",
        "tree_even": "#f8fafc",
        "tree_head": "#f1f5f9",
        "card_muted": "#64748b",
        "report_bg": "#ffffff",
        "report_fg": "#0f172a",
    },
    "dark": {
        "bg": "#0f172a",
        "surface": "#1e293b",
        "ink": "#f8fafc",
        "muted": "#94a3b8",
        "teal": "#2dd4bf",
        "teal_hover": "#14b8a6",
        "teal_pressed": "#0d9488",
        "line": "#334155",
        "red": "#f87171",
        "header_bg": "#020617",
        "header_fg": "#f8fafc",
        "header_sub": "#64748b",
        "tree_bg": "#1e293b",
        "tree_fg": "#f8fafc",
        "tree_even": "#0f172a",
        "tree_head": "#0f172a",
        "card_muted": "#94a3b8",
        "report_bg": "#1e293b",
        "report_fg": "#f8fafc",
    }
}

BG, SURFACE, INK, MUTED = "#f8fafc", "#ffffff", "#0f172a", "#64748b"
TEAL, LINE, RED = "#0d9488", "#e2e8f0", "#dc2626"

EXAMPLES = {
    "3 nút · SLACK / PV / PQ": "luoi_3_nut.json",
    "9 nút · MATPOWER case9": "luoi_9_nut.json",
    "14 nút · IEEE 14-bus": "luoi_14_nut.json",
    "30 nút · IEEE 30-bus": "luoi_30_nut.json",
    "3 nút · PV chạm Qmax": "luoi_3_nut_gioi_han_q.json"
}

BUS_COLUMNS = [
    ("id", "Nút", 65), ("type_final", "Loại sau giải", 115),
    ("vm_pu", "U (p.u.)", 100), ("va_deg", "Góc (độ)", 100),
    ("voltage_kv", "U dây (kV)", 110), ("pg_mw", "Pg (MW)", 105),
    ("qg_mvar", "Qg (Mvar)", 110), ("pd_mw", "Pd (MW)", 105), ("qd_mvar", "Qd (Mvar)", 110)
]

BRANCH_COLUMNS = [
    ("id", "Nhánh", 85), ("from_bus", "Đầu", 65), ("to_bus", "Cuối", 65),
    ("status", "Đóng", 75), ("p_from_mw", "Pf (MW)", 105), ("q_from_mvar", "Qf (Mvar)", 110),
    ("p_to_mw", "Pt (MW)", 105), ("q_to_mvar", "Qt (Mvar)", 110), ("p_loss_mw", "ΔP (MW)", 105),
    ("i_from_ka", "If (kA)", 100), ("i_to_ka", "It (kA)", 100), ("loading_percent", "Tải (%)", 100)
]


class PowerFlowApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PowerFlow · Chế độ xác lập lưới điện")
        width = min(1380, self.winfo_screenwidth() - 60)
        height = min(860, self.winfo_screenheight() - 80)
        self.geometry(f"{width}x{height}")
        self.minsize(1040, 720)

        self.theme_mode = "light"
        self._current_tone = "idle"
        self._calc_start_time = 0.0
        self._syncing_editor = False

        self.result = self.result_source = self.input_path = None
        self.saved_text = ""
        self.is_running = self._closed = False
        self._validation_after = self._poll_after = None
        self._job_limits = {}
        self.worker_queue = queue.Queue()
        self.bench_queue = queue.Queue()
        self.n1_queue = queue.Queue()

        self.tolerance = tk.StringVar(value="1e-8")
        self.max_iter = tk.StringVar(value="50")
        self.enforce_q = tk.BooleanVar(value=True)
        self.solver_method = tk.StringVar(value="Newton–Raphson (Chuẩn CN)")
        self.status = tk.StringVar(value="Sẵn sàng")
        self.state_text = tk.StringVar(value="CHỜ TÍNH TOÁN")
        self.file_label = tk.StringVar()
        self.case_info = tk.StringVar()
        self.input_feedback = tk.StringVar()
        self.example = tk.StringVar(value=next(iter(EXAMPLES)))

        self.filter_vars, self.table_rows, self.tables = {}, {}, {}
        self.table_counts, self.table_sorts = {}, {}

        self._configure_styles()
        self._build_header()
        self._build_footer()
        self._build_body()

        for var in (self.tolerance, self.max_iter, self.enforce_q, self.solver_method):
            var.trace_add("write", self._options_changed)
        self.editor.bind("<<Modified>>", self.on_edit)

        for shortcut, command in (
            ("<Control-o>", self.open_case), ("<Control-s>", self.save_case),
            ("<F5>", self.calculate), ("<Control-Return>", self.calculate),
            ("<F1>", self.show_help), ("<Control-Shift-F>", self.format_json),
            ("<Control-t>", self.toggle_theme)
        ):
            self.bind(shortcut, lambda _event, fn=command: self._shortcut(fn))

        self.protocol("WM_DELETE_WINDOW", self.close)
        self.load_example("luoi_3_nut.json", confirm=False)

    def _configure_styles(self):
        theme = THEMES[self.theme_mode]
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        style.configure(".", font=("Segoe UI", 10), background=theme["bg"], foreground=theme["ink"])
        style.configure("TFrame", background=theme["bg"])
        style.configure("Card.TFrame", background=theme["surface"])
        style.configure("TLabel", background=theme["bg"], foreground=theme["ink"])
        style.configure("Muted.TLabel", foreground=theme["muted"])
        style.configure("CardMuted.TLabel", background=theme["surface"], foreground=theme["card_muted"], font=("Segoe UI", 9))
        style.configure("Section.TLabel", background=theme["surface"], foreground=theme["ink"], font=("Segoe UI", 11, "bold"))

        style.configure("TButton", padding=(11, 7), background=theme["surface"], foreground=theme["ink"],
                        bordercolor=theme["line"], lightcolor=theme["surface"], darkcolor=theme["surface"],
                        focusthickness=1, focuscolor=theme["teal"])
        style.map("TButton",
                  background=[("active", "#e2e8f0" if self.theme_mode == "light" else "#334155"),
                              ("pressed", "#cbd5e1" if self.theme_mode == "light" else "#475569")],
                  foreground=[("disabled", "#94a3b8" if self.theme_mode == "light" else "#64748b")])

        style.configure("Small.TButton", padding=(8, 4), font=("Segoe UI", 9))

        style.configure("Primary.TButton", background=theme["teal"], foreground="white",
                        bordercolor=theme["teal"], lightcolor=theme["teal"], darkcolor=theme["teal"],
                        font=("Segoe UI", 11, "bold"), padding=(16, 10))
        style.map("Primary.TButton",
                  background=[("disabled", "#94a3b8" if self.theme_mode == "light" else "#475569"),
                              ("pressed", theme["teal_pressed"]),
                              ("active", theme["teal_hover"])],
                  foreground=[("disabled", "white")])

        style.configure("TEntry", fieldbackground=theme["surface"], foreground=theme["ink"],
                        bordercolor=theme["line"], padding=6)
        style.map("TEntry", bordercolor=[("invalid", theme["red"]), ("focus", theme["teal"])])

        style.configure("TCombobox", fieldbackground=theme["surface"], background=theme["surface"],
                        foreground=theme["ink"], padding=5, bordercolor=theme["line"], arrowsize=13)
        style.map("TCombobox",
                  fieldbackground=[("readonly", theme["surface"])],
                  selectbackground=[("readonly", theme["surface"])],
                  selectforeground=[("readonly", theme["ink"])])

        style.configure("TCheckbutton", background=theme["surface"], foreground=theme["ink"], padding=(0, 4))
        style.map("TCheckbutton", background=[("active", theme["surface"])])

        style.configure("TNotebook", background=theme["bg"], borderwidth=0, tabmargins=(0, 0, 0, 8))
        style.configure("TNotebook.Tab", padding=(14, 9), background=theme["bg"], foreground=theme["muted"],
                        font=("Segoe UI", 10, "bold"))
        style.map("TNotebook.Tab",
                  background=[("selected", theme["surface"]), ("active", "#e2e8f0" if self.theme_mode == "light" else "#334155")],
                  foreground=[("selected", theme["teal"])])

        style.configure("Treeview", rowheight=34, fieldbackground=theme["tree_bg"], background=theme["tree_bg"],
                        foreground=theme["tree_fg"], borderwidth=0, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background=theme["tree_head"], foreground=theme["muted"],
                        padding=(8, 9), font=("Segoe UI", 9, "bold"), relief="flat")
        style.map("Treeview",
                  background=[("selected", "#0d9488" if self.theme_mode == "dark" else "#ccfbf1")],
                  foreground=[("selected", "white" if self.theme_mode == "dark" else "#0f172a")])

        style.configure("Horizontal.TProgressbar", background=theme["teal"],
                        troughcolor="#e2e8f0" if self.theme_mode == "light" else "#1e293b",
                        borderwidth=0, thickness=3)
        style.configure("TPanedwindow", background=theme["bg"])
        for orientation in ("Vertical", "Horizontal"):
            style.configure(f"{orientation}.TScrollbar", arrowsize=12,
                            background="#cbd5e1" if self.theme_mode == "light" else "#334155",
                            troughcolor=theme["bg"], borderwidth=0)

    def _build_header(self):
        theme = THEMES[self.theme_mode]
        self.header = tk.Frame(self, background=theme["header_bg"], padx=20, pady=12)
        self.header.pack(fill="x")

        # Logo mark
        self.header_mark = tk.Canvas(self.header, width=38, height=38, bg=theme["teal"], highlightthickness=0)
        self.header_mark.pack(side="left", padx=(0, 12))
        self.header_mark.create_line(6, 21, 14, 21, 19, 9, 23, 29, 28, 17, 33, 17, fill="white", width=2.5, joinstyle="round")

        self.header_title_frame = tk.Frame(self.header, bg=theme["header_bg"])
        self.header_title_frame.pack(side="left")

        lbl1 = tk.Label(self.header_title_frame, text="PowerFlow", bg=theme["header_bg"], fg=theme["header_fg"], font=("Segoe UI", 18, "bold"))
        lbl1.pack(anchor="w")
        lbl2 = tk.Label(self.header_title_frame, text="PHÂN TÍCH CHẾ ĐỘ XÁC LẬP LƯỚI ĐIỆN", bg=theme["header_bg"], fg=theme["header_sub"], font=("Segoe UI", 8, "bold"))
        lbl2.pack(anchor="w", pady=(1, 0))

        # Đèn báo trạng thái trực quan thời gian thực
        self.header_status_frame = tk.Frame(self.header, bg=theme["header_bg"])
        self.header_status_frame.pack(side="left", padx=(24, 0))
        self.header_status_dot = tk.Label(
            self.header_status_frame, text="● Sẵn sàng",
            bg=theme["header_bg"], fg="#10b981", font=("Segoe UI", 9, "bold")
        )
        self.header_status_dot.pack(side="left")

        # Nút chuyển giao diện Sáng / Tối
        self.theme_btn = ttk.Button(self.header, text="🌙 Chế độ tối", command=self.toggle_theme, style="Small.TButton")
        self.theme_btn.pack(side="right", padx=(8, 0))

        btn_excel_sample = ttk.Button(self.header, text="Excel mẫu", command=self.export_excel_template, style="Small.TButton")
        btn_excel_sample.pack(side="right", padx=(8, 0))

        btn_help = ttk.Button(self.header, text="Hướng dẫn  F1", command=self.show_help, style="Small.TButton")
        btn_help.pack(side="right", padx=(8, 0))

        lbl3 = tk.Label(self.header, text="4 Phương pháp trào lưu\nNR · FDPF · GS · DC", justify="right",
                        bg=theme["header_bg"], fg=theme["header_sub"], font=("Segoe UI", 9))
        lbl3.pack(side="right", padx=(0, 12))

        self._header_labels = [lbl1, lbl2, lbl3, self.header_status_dot]

    def toggle_theme(self):
        self.theme_mode = "dark" if self.theme_mode == "light" else "light"
        self.theme_btn.configure(text="☀️ Chế độ sáng" if self.theme_mode == "dark" else "🌙 Chế độ tối")
        self._apply_theme()

    def _apply_theme(self):
        theme = THEMES[self.theme_mode]
        self.configure(background=theme["bg"])
        self._configure_styles()
        self.header.configure(background=theme["header_bg"])
        self.header_title_frame.configure(background=theme["header_bg"])
        if hasattr(self, "header_status_frame"):
            self.header_status_frame.configure(background=theme["header_bg"])
        self.header_mark.configure(bg=theme["teal"])
        for lbl in self._header_labels:
            lbl.configure(background=theme["header_bg"])
            if lbl == self._header_labels[0]:
                lbl.configure(fg=theme["header_fg"])
            elif hasattr(self, "header_status_dot") and lbl == self.header_status_dot:
                pass  # Giữ nguyên màu trạng thái đèn báo
            else:
                lbl.configure(fg=theme["header_sub"])

        self.dashboard.apply_theme(self.theme_mode)
        self.diagram.apply_theme(self.theme_mode)
        self.json_editor.apply_theme(self.theme_mode)
        if hasattr(self, "table_editor"):
            self.table_editor.apply_theme(self.theme_mode)
        self.report.configure(background=theme["report_bg"], foreground=theme["report_fg"])

        for kind in self.tables:
            self._configure_table_tags(self.tables[kind])
            self.render_table(kind)

        if hasattr(self, "n1_table"):
            self._configure_n1_table_tags()
            self._render_n1_rows()
        if hasattr(self, "compare_bus_table"):
            self._configure_table_tags(self.compare_bus_table)
            self._configure_table_tags(self.compare_branch_table)
        if hasattr(self, "bench_kpi_table"):
            self._configure_table_tags(self.bench_kpi_table)
            self._configure_table_tags(self.bench_bus_table)
            self._configure_table_tags(self.bench_branch_table)
        if hasattr(self, "n1_cards"):
            for card in self.n1_cards.values():
                card.configure(bg=theme["surface"])
        if hasattr(self, "compare_cards"):
            for card in self.compare_cards.values():
                card.configure(bg=theme["surface"])
        if hasattr(self, "bench_cards"):
            for card in self.bench_cards:
                card.configure(bg=theme["surface"], highlightbackground=theme["line"])
                for child in card.winfo_children():
                    child.configure(bg=theme["surface"])
        if hasattr(self, "bench_theory_text"):
            self.bench_theory_text.configure(background=theme["report_bg"], foreground=theme["report_fg"])

        self._set_state(self.state_text.get(), self._current_tone)

    def _build_body(self):
        self.body = ttk.Panedwindow(self, orient="horizontal")
        self.body.pack(fill="both", expand=True, padx=18, pady=(14, 0))

        left = ttk.Frame(self.body, style="Card.TFrame", padding=14, width=420)
        right = ttk.Frame(self.body, padding=(14, 0, 0, 0))
        self.body.add(left, weight=0)
        self.body.add(right, weight=1)

        self._build_input(left)

        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill="both", expand=True)

        self.dashboard = Dashboard(self.tabs)
        self.tabs.add(self.dashboard, text="Tổng quan")

        self.diagram = NetworkDiagram(self.tabs)
        self.tabs.add(self.diagram, text="Sơ đồ lưới")

        self.bus_table = self._build_table_tab("buses", "Điện áp nút", BUS_COLUMNS, "U dây: kV · Công suất: MW / Mvar tổng ba pha")
        self.branch_table = self._build_table_tab("branches", "Công suất nhánh", BRANCH_COLUMNS,
                                                  "P, Q dương: từ nút đi vào nhánh · —: thiếu cơ sở hoặc định mức")

        self._build_contingency_tab()
        self._build_scenario_compare_tab()
        self._build_solvers_benchmark_tab()

        report_frame = ttk.Frame(self.tabs, style="Card.TFrame", padding=14)
        self.tabs.add(report_frame, text="Báo cáo")

        toolbar = ttk.Frame(report_frame, style="Card.TFrame")
        toolbar.pack(fill="x", pady=(0, 10))
        ttk.Label(toolbar, text="Báo cáo tính toán chi tiết", style="Section.TLabel").pack(side="left")
        ttk.Button(toolbar, text="Sao chép toàn bộ", command=self.copy_report, style="Small.TButton").pack(side="right")

        self.report = ScrolledText(report_frame, wrap="none", font=("Consolas", 10), state="disabled",
                                   background=SURFACE, foreground=INK, borderwidth=0, padx=8, pady=8)
        self.report.pack(fill="both", expand=True)
        report_x = ttk.Scrollbar(report_frame, orient="horizontal", command=self.report.xview)
        report_x.pack(fill="x")
        self.report.configure(xscrollcommand=report_x.set)

    def _build_input(self, parent):
        heading = ttk.Frame(parent, style="Card.TFrame")
        heading.pack(fill="x")
        ttk.Label(heading, text="01  Dữ liệu lưới", style="Section.TLabel").pack(side="left")
        ttk.Button(heading, text="Mở…", command=self.open_case, style="Small.TButton").pack(side="right")
        ttk.Button(heading, text="Lưu…", command=self.save_case, style="Small.TButton").pack(side="right", padx=4)

        ttk.Label(parent, textvariable=self.file_label, style="CardMuted.TLabel").pack(anchor="w", pady=(5, 6))

        examples = ttk.Frame(parent, style="Card.TFrame")
        examples.pack(fill="x")
        ttk.Combobox(examples, textvariable=self.example, values=list(EXAMPLES), state="readonly", width=22).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(examples, text="Nạp mẫu", command=lambda: self.load_example(EXAMPLES[self.example.get()]), style="Small.TButton").pack(side="right")

        self.case_label = ttk.Label(parent, textvariable=self.case_info, style="CardMuted.TLabel", wraplength=330)
        self.case_label.pack(fill="x", pady=5)

        # Tab chuyển đổi nhập liệu: Bảng trực quan hoặc Code JSON
        self.input_tabs = ttk.Notebook(parent)
        self.input_tabs.pack(fill="both", expand=True)

        # Tab 1: Bảng dữ liệu trực quan
        self.table_editor = TableInputEditor(self.input_tabs, on_change=self._on_table_input_changed)
        self.input_tabs.add(self.table_editor, text="Bảng dữ liệu")

        # Tab 2: Code JSON
        self.json_frame = ttk.Frame(self.input_tabs, style="Card.TFrame")
        self.input_tabs.add(self.json_frame, text="Mã JSON")

        toolbar = ttk.Frame(self.json_frame, style="Card.TFrame")
        toolbar.pack(fill="x", pady=(2, 4))
        ttk.Label(toolbar, text="JSON", style="CardMuted.TLabel").pack(side="left")
        ttk.Button(toolbar, text="Định dạng", command=self.format_json, style="Small.TButton").pack(side="right")
        ttk.Button(toolbar, text="Kiểm tra", command=self.validate_input, style="Small.TButton").pack(side="right", padx=4)

        self.json_editor = JsonEditor(self.json_frame)
        self.json_editor.pack(fill="both", expand=True)
        self.editor = self.json_editor.text
        self.editor.configure(width=35, height=8)

        ttk.Label(self.json_frame, textvariable=self.json_editor.cursor, style="CardMuted.TLabel").pack(anchor="e", pady=(3, 2))

        self.input_tabs.bind("<<NotebookTabChanged>>", self._on_input_tab_changed)

        self.feedback_label = ttk.Label(parent, textvariable=self.input_feedback, style="CardMuted.TLabel", wraplength=330)
        self.feedback_label.pack(fill="x", pady=(4, 6))

        ttk.Separator(parent).pack(fill="x", pady=(0, 6))

        ttk.Label(parent, text="02  Thiết lập bộ giải", style="Section.TLabel").pack(anchor="w")

        settings = ttk.Frame(parent, style="Card.TFrame")
        settings.pack(fill="x", pady=(6, 4))
        settings.columnconfigure((0, 1), weight=1)

        ttk.Label(settings, text="Phương pháp giải", style="CardMuted.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self.method_combobox = ttk.Combobox(settings, textvariable=self.solver_method,
                                            values=[label for label, _ in SOLVER_METHODS],
                                            state="readonly")
        self.method_combobox.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 6))

        ttk.Label(settings, text="Dung sai (p.u.)", style="CardMuted.TLabel").grid(row=2, column=0, sticky="w")
        ttk.Label(settings, text="Bước tối đa / lượt", style="CardMuted.TLabel").grid(row=2, column=1, sticky="w", padx=(10, 0))

        self.tolerance_entry = ttk.Entry(settings, textvariable=self.tolerance, width=10)
        self.tolerance_entry.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        self.iteration_entry = ttk.Entry(settings, textvariable=self.max_iter, width=10)
        self.iteration_entry.grid(row=3, column=1, sticky="ew", padx=(10, 0), pady=(4, 0))

        ttk.Checkbutton(parent, text="Áp dụng giới hạn Q tại nút PV", variable=self.enforce_q).pack(anchor="w", pady=4)

        self.run_button = ttk.Button(parent, text="⚡ Tính toán trào lưu     F5", command=self.calculate, style="Primary.TButton")
        self.run_button.pack(fill="x", pady=(4, 0))

        progress_track = tk.Frame(parent, background="#e2e8f0", height=3)
        progress_track.pack(fill="x", pady=(4, 0))
        self.progress = ttk.Progressbar(progress_track, mode="indeterminate")
        self.progress.place(x=0, y=0, relwidth=1, relheight=1)

        parent.columnconfigure(0, weight=1)
        input_widgets = [(child, child.pack_info().get("pady", 0)) for child in parent.winfo_children()]
        for child, _spacing in input_widgets:
            child.pack_forget()
        for row, (child, spacing) in enumerate(input_widgets):
            child.grid(row=row, column=0, sticky="nsew" if child is self.input_tabs else "ew", pady=spacing)
            if child is self.input_tabs:
                parent.rowconfigure(row, weight=1, minsize=140)
        parent.bind("<Configure>", lambda event: self._resize_input(event.width))

    def _resize_input(self, width):
        for label in (self.case_label, self.feedback_label):
            label.configure(wraplength=max(180, width - 34))

    def _on_table_input_changed(self):
        """Khi người dùng chỉnh sửa trên bảng, đồng bộ sang mã JSON."""
        if self._syncing_editor:
            return
        self._syncing_editor = True
        try:
            case_data = self.table_editor.get_case_data()
            formatted = json.dumps(case_data, ensure_ascii=False, indent=2) + "\n"
            if formatted != self.text():
                self.editor.delete("1.0", "end")
                self.editor.insert("1.0", formatted)
                self.json_editor.refresh()
                self.on_edit()
        finally:
            self._syncing_editor = False

    def _on_input_tab_changed(self, _event=None):
        """Khi chuyển tab giữa Bảng và JSON, đồng bộ bảng từ nội dung JSON."""
        if self._syncing_editor:
            return
        selected_idx = self.input_tabs.index("current")
        if selected_idx == 0:  # Chuyển sang tab Bảng
            try:
                parsed = parse_case(self.text())
                self._syncing_editor = True
                self.table_editor.set_case_data(parsed)
            except Exception:
                pass
            finally:
                self._syncing_editor = False

    def _configure_table_tags(self, tree):
        if self.theme_mode == "dark":
            tree.tag_configure("even", background="#1e293b")
            tree.tag_configure("odd", background="#0f172a")
            tree.tag_configure("slack", background="#0c4a6e", foreground="#38bdf8")
            tree.tag_configure("pv", background="#064e3b", foreground="#4ade80")
            tree.tag_configure("switched", background="#451a03", foreground="#fbbf24")
            tree.tag_configure("warning", background="#451a03", foreground="#fcd34d")
            tree.tag_configure("overload", background="#450a0a", foreground="#f87171")
            tree.tag_configure("heavy", background="#451a03", foreground="#fbbf24")
        else:
            tree.tag_configure("even", background="#f8fafc")
            tree.tag_configure("odd", background="#ffffff")
            tree.tag_configure("slack", background="#e0f2fe", foreground="#0369a1")
            tree.tag_configure("pv", background="#dcfce7", foreground="#15803d")
            tree.tag_configure("switched", background="#fef3c7", foreground="#b45309")
            tree.tag_configure("warning", background="#fffbeb", foreground="#92400e")
            tree.tag_configure("overload", background="#fee2e2", foreground="#b91c1c")
            tree.tag_configure("heavy", background="#fef3c7", foreground="#b45309")

    def _build_table_tab(self, kind, title, columns, hint):
        frame = ttk.Frame(self.tabs, style="Card.TFrame", padding=14)
        self.tabs.add(frame, text=title)

        toolbar = ttk.Frame(frame, style="Card.TFrame")
        toolbar.pack(fill="x", pady=(0, 10))

        ttk.Label(toolbar, text="Tìm kiếm:", style="CardMuted.TLabel").pack(side="left", padx=(0, 6))
        variable = tk.StringVar()
        self.filter_vars[kind] = variable
        ttk.Entry(toolbar, textvariable=variable, width=18).pack(side="left", fill="x", expand=True)
        ttk.Button(toolbar, text="Xóa lọc", style="Small.TButton", command=lambda: variable.set("")).pack(side="left", padx=5)

        ttk.Button(toolbar, text="Sao chép dòng", style="Small.TButton", command=lambda: self.copy_table(kind)).pack(side="right")

        table_frame = ttk.Frame(frame, style="Card.TFrame")
        table_frame.pack(fill="both", expand=True)
        tree = self.make_table(table_frame, columns)
        self.tables[kind], self.table_rows[kind], self.table_sorts[kind] = tree, [], (None, False)

        for key, col_title, _width in columns:
            tree.heading(key, text=col_title, command=lambda c=key: self.sort_table(kind, c))

        self._configure_table_tags(tree)
        tree.bind("<Control-c>", lambda _event: self._shortcut(lambda: self.copy_table(kind)))

        self.table_counts[kind] = tk.StringVar(value="Chưa có kết quả")
        ttk.Label(frame, textvariable=self.table_counts[kind], style="CardMuted.TLabel").pack(anchor="w", pady=(8, 2))

        hint_label = ttk.Label(frame, text=hint + "\nBấm tiêu đề cột để sắp xếp · SLACK (Lam) · PV (Lục) · PV chuyển PQ (Vàng cam) · Quá tải (Đỏ)",
                               style="CardMuted.TLabel", wraplength=600)
        hint_label.pack(fill="x")
        frame.bind("<Configure>", lambda event: hint_label.configure(wraplength=max(180, event.width - 30)))
        variable.trace_add("write", lambda *_: self.render_table(kind))
        return tree

    @staticmethod
    def make_table(parent, columns):
        tree = ttk.Treeview(parent, columns=[col[0] for col in columns], show="headings", selectmode="extended")
        for key, title, width in columns:
            tree.heading(key, text=title)
            tree.column(key, width=width, minwidth=60,
                        anchor="w" if key in {"id", "type_final", "from_bus", "to_bus"} else "e",
                        stretch=False)
        xbar = ttk.Scrollbar(parent, orient="horizontal", command=tree.xview)
        ybar = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        return tree

    def _configure_n1_table_tags(self):
        if not hasattr(self, "n1_table"):
            return
        if self.theme_mode == "dark":
            self.n1_table.tag_configure("even", background="#1e293b")
            self.n1_table.tag_configure("odd", background="#0f172a")
            self.n1_table.tag_configure("safe", background="#064e3b", foreground="#4ade80")
            self.n1_table.tag_configure("warning", background="#451a03", foreground="#fbbf24")
            self.n1_table.tag_configure("critical", background="#450a0a", foreground="#f87171")
        else:
            self.n1_table.tag_configure("even", background="#f8fafc")
            self.n1_table.tag_configure("odd", background="#ffffff")
            self.n1_table.tag_configure("safe", background="#dcfce7", foreground="#15803d")
            self.n1_table.tag_configure("warning", background="#fef3c7", foreground="#b45309")
            self.n1_table.tag_configure("critical", background="#fee2e2", foreground="#b91c1c")

    def _build_contingency_tab(self):
        self.n1_frame = ttk.Frame(self.tabs, style="Card.TFrame", padding=14)
        self.tabs.add(self.n1_frame, text="🛡️ Quét sự cố N-1")

        toolbar = ttk.Frame(self.n1_frame, style="Card.TFrame")
        toolbar.pack(fill="x", pady=(0, 10))

        self.btn_run_n1 = ttk.Button(
            toolbar, text="⚡ Chạy phân tích N-1", command=self.run_n1_analysis, style="Primary.TButton"
        )
        self.btn_run_n1.pack(side="left")

        self.btn_export_n1 = ttk.Button(
            toolbar, text="Xuất bảng N-1...", command=self.export_n1_results, style="Small.TButton"
        )
        self.btn_export_n1.pack(side="left", padx=8)

        self.btn_view_n1_diagram = ttk.Button(
            toolbar, text="🔍 Xem trên sơ đồ", command=self.view_contingency_on_diagram, style="Small.TButton"
        )
        self.btn_view_n1_diagram.pack(side="left", padx=2)

        self.n1_status_var = tk.StringVar(value="Sẵn sàng quét sự cố cho tất cả nhánh trong hệ thống.")
        ttk.Label(toolbar, textvariable=self.n1_status_var, style="CardMuted.TLabel").pack(side="right", padx=6)

        kpi_row = ttk.Frame(self.n1_frame, style="Card.TFrame")
        kpi_row.pack(fill="x", pady=(0, 10))
        kpi_row.columnconfigure((0, 1, 2, 3), weight=1)

        self.n1_cards = {}
        card_configs = [
            ("total", "Tổng số kịch bản", "—", "#0f172a"),
            ("safe", "An toàn (Không vi phạm)", "—", "#15803d"),
            ("warning", "Cảnh báo (Quá tải/Áp)", "—", "#b45309"),
            ("critical", "Nguy cấp (Rã lưới / Không hội tụ)", "—", "#b91c1c")
        ]
        for col, (key, title, init_val, fg_color) in enumerate(card_configs):
            card = ttk.Frame(kpi_row, style="Card.TFrame", padding=(10, 8), borderwidth=1, relief="solid")
            card.grid(row=0, column=col, sticky="nsew", padx=4)
            ttk.Label(card, text=title, style="CardMuted.TLabel").pack(anchor="w")
            lbl_val = tk.Label(card, text=init_val, font=("Segoe UI", 13, "bold"), fg=fg_color, bg=SURFACE)
            lbl_val.pack(anchor="w", pady=(4, 0))
            self.n1_cards[key] = lbl_val

        table_frame = ttk.Frame(self.n1_frame, style="Card.TFrame")
        table_frame.pack(fill="both", expand=True)

        n1_cols = [
            ("contingency_id", "Kịch bản N-1", 130),
            ("branch_id", "Nhánh cắt", 80),
            ("from_to", "Tuyến", 80),
            ("status_text", "Đánh giá", 110),
            ("pi_score", "Điểm PI", 80),
            ("max_loading", "Tải max (%)", 90),
            ("worst_bus", "Nút sụt áp nhất", 130),
            ("detail_message", "Chi tiết vi phạm & cảnh báo", 320)
        ]
        self.n1_table = ttk.Treeview(
            table_frame, columns=[col[0] for col in n1_cols], show="headings", selectmode="browse"
        )
        for key, title, width in n1_cols:
            self.n1_table.heading(key, text=title, command=lambda c=key: self.sort_n1_table(c))
            self.n1_table.column(
                key, width=width, minwidth=60,
                anchor="w" if key in ("contingency_id", "detail_message", "worst_bus", "status_text") else "e"
            )

        n1_xbar = ttk.Scrollbar(table_frame, orient="horizontal", command=self.n1_table.xview)
        n1_ybar = ttk.Scrollbar(table_frame, orient="vertical", command=self.n1_table.yview)
        self.n1_table.configure(xscrollcommand=n1_xbar.set, yscrollcommand=n1_ybar.set)
        self.n1_table.grid(row=0, column=0, sticky="nsew")
        n1_ybar.grid(row=0, column=1, sticky="ns")
        n1_xbar.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        self._configure_n1_table_tags()
        self.n1_table.bind("<Double-1>", lambda _e: self.view_contingency_on_diagram())

        self.n1_results_data = []
        self.n1_sort_col = "pi_score"
        self.n1_sort_desc = True

        hint = ttk.Label(
            self.n1_frame,
            text="Ghi chú: Chỉ số PI (Performance Index) đánh giá mức căng thẳng của hệ thống. Nhấp đúp vào sự cố để định vị trên sơ đồ đơn tuyến.",
            style="CardMuted.TLabel"
        )
        hint.pack(anchor="w", pady=(6, 0))

    def run_n1_analysis(self):
        if not self.validate_input():
            messagebox.showerror("Dữ liệu không hợp lệ", "Vui lòng sửa các lỗi dữ liệu trước khi quét sự cố N-1.", parent=self)
            return
        data = parse_case(self.text())
        tol, max_iter = self._read_options()
        enforce_q = self.enforce_q.get()

        self.btn_run_n1.configure(state="disabled", text="Đang quét N-1…")
        self.n1_status_var.set("Đang chạy mô phỏng ngắt từng nhánh trong hệ thống...")
        self.update_idletasks()

        def run():
            try:
                res = run_n1_contingency_analysis(data, tolerance=tol, max_iterations=max_iter, enforce_q_limits=enforce_q)
                self.n1_queue.put((res, None))
            except Exception as e:
                self.n1_queue.put((None, e))

        threading.Thread(target=run, daemon=True).start()
        self._poll_n1()

    def _poll_n1(self):
        if self._closed:
            return
        try:
            res, err = self.n1_queue.get_nowait()
            self._on_n1_finished(res, err)
        except queue.Empty:
            self.after(50, self._poll_n1)

    def _on_n1_finished(self, res, error):
        self.btn_run_n1.configure(state="normal", text="⚡ Chạy phân tích N-1")
        if error:
            messagebox.showerror("Lỗi phân tích N-1", str(error), parent=self)
            self.n1_status_var.set(f"Lỗi: {error}")
            return

        self.n1_results_data = res.get("contingencies", [])
        self.n1_cards["total"].configure(text=str(res.get("total_contingencies", len(self.n1_results_data))))
        self.n1_cards["safe"].configure(text=str(res.get("secure_count", 0)))
        self.n1_cards["warning"].configure(text=str(res.get("warning_count", 0)))
        self.n1_cards["critical"].configure(text=str(res.get("critical_count", 0)))

        self.n1_status_var.set(
            f"Hoàn thành: {res.get('total_contingencies')} sự cố ({res.get('secure_count')} an toàn, "
            f"{res.get('warning_count')} cảnh báo, {res.get('critical_count')} nguy cấp)"
        )
        self._render_n1_rows()

    def sort_n1_table(self, key):
        if self.n1_sort_col == key:
            self.n1_sort_desc = not self.n1_sort_desc
        else:
            self.n1_sort_col = key
            self.n1_sort_desc = True
        self._render_n1_rows()

    def _render_n1_rows(self):
        self.n1_table.delete(*self.n1_table.get_children())
        rows = list(self.n1_results_data)
        if not rows:
            return

        key = self.n1_sort_col
        rev = self.n1_sort_desc
        if key:
            rows.sort(key=lambda r: (r.get(key) is None, r.get(key) if r.get(key) is not None else 0), reverse=rev)

        for i, r in enumerate(rows):
            from_to = f"{r.get('from_bus')} ➔ {r.get('to_bus')}"
            worst_v_txt = f"Nút {r.get('worst_voltage_bus')} ({r.get('min_voltage'):.4f} pu)" if r.get("worst_voltage_bus") and r.get("min_voltage") is not None else "—"
            max_load_txt = f"{r.get('max_loading'):.1f}%" if r.get("max_loading") is not None else "—"

            vals = [
                r.get("contingency_id", ""),
                r.get("branch_id", ""),
                from_to,
                r.get("status_text", ""),
                f"{r.get('pi_score', 0.0):.2f}",
                max_load_txt,
                worst_v_txt,
                r.get("detail_message", "")
            ]

            sev = r.get("severity", "SECURE")
            tag = "safe" if sev == "SECURE" else ("warning" if sev == "WARNING" else "critical")
            self.n1_table.insert("", "end", values=vals, tags=(tag,))

    def view_contingency_on_diagram(self):
        sel = self.n1_table.selection()
        if not sel:
            messagebox.showinfo("Xem trên sơ đồ", "Hãy chọn một dòng sự cố trong bảng để xem.", parent=self)
            return
        item_vals = self.n1_table.item(sel[0], "values")
        if not item_vals:
            return
        branch_id = item_vals[1]
        from_to = item_vals[2]
        detail = item_vals[7]

        # Chuyển tab sang Sơ đồ lưới
        self.tabs.select(self.diagram)
        # Định vị nút đầu của nhánh
        parts = from_to.split("➔")
        if len(parts) == 2:
            from_bus = parts[0].strip()
            self.diagram.locate_bus(from_bus)
            self.diagram.info_label.configure(
                text=f"SỰ CỐ N-1: Ngắt nhánh {branch_id} ({from_to}) · {detail}"
            )

    def export_n1_results(self):
        if not self.n1_results_data:
            messagebox.showinfo("Xuất kết quả N-1", "Chưa có kết quả phân tích N-1 để xuất.", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Xuất bảng sự cố N-1",
            defaultextension=".csv",
            filetypes=[("Bảng tính CSV", "*.csv"), ("Tất cả", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["Kịch bản N-1", "Nhánh cắt", "Đầu", "Cuối", "Đánh giá", "Điểm PI", "Tải max (%)", "Nút sụt áp nhất", "Chi tiết vi phạm"])
                for r in self.n1_results_data:
                    worst_v_txt = f"Nút {r.get('worst_voltage_bus')} ({r.get('min_voltage'):.4f} pu)" if r.get("worst_voltage_bus") else "—"
                    writer.writerow([
                        r.get("contingency_id"),
                        r.get("branch_id"),
                        r.get("from_bus"),
                        r.get("to_bus"),
                        r.get("status_text"),
                        r.get("pi_score"),
                        r.get("max_loading"),
                        worst_v_txt,
                        r.get("detail_message")
                    ])
            messagebox.showinfo("Thành công", f"Đã xuất bảng sự cố N-1 ra:\n{path}", parent=self)
        except Exception as e:
            messagebox.showerror("Lỗi xuất tệp", str(e), parent=self)

    def _build_scenario_compare_tab(self):
        self.compare_frame = ttk.Frame(self.tabs, style="Card.TFrame", padding=14)
        self.tabs.add(self.compare_frame, text="⚖️ So sánh kịch bản")

        toolbar = ttk.Frame(self.compare_frame, style="Card.TFrame")
        toolbar.pack(fill="x", pady=(0, 10))

        self.btn_set_base = ttk.Button(
            toolbar, text="📌 Lưu kết quả hiện tại làm Base Case",
            command=self.set_as_base_case, style="Small.TButton"
        )
        self.btn_set_base.pack(side="left")

        self.btn_clear_base = ttk.Button(
            toolbar, text="Xóa Base Case",
            command=self.clear_base_case, style="Small.TButton"
        )
        self.btn_clear_base.pack(side="left", padx=6)

        self.base_case_info = tk.StringVar(value="Base Case: [Chưa lưu] (Hãy giải F5 rồi bấm nút để lưu kịch bản cơ sở)")
        ttk.Label(toolbar, textvariable=self.base_case_info, style="CardMuted.TLabel").pack(side="left", padx=12)

        delta_kpi_row = ttk.Frame(self.compare_frame, style="Card.TFrame")
        delta_kpi_row.pack(fill="x", pady=(0, 10))
        delta_kpi_row.columnconfigure((0, 1, 2), weight=1)

        self.compare_cards = {}
        for col, (key, title) in enumerate([
            ("loss_delta", "Biến thiên tổn thất ΔPloss"),
            ("volt_delta", "Độ lệch điện áp lớn nhất |ΔU|max"),
            ("load_delta", "Biến thiên mang tải nhánh max |ΔLoad|max")
        ]):
            card = ttk.Frame(delta_kpi_row, style="Card.TFrame", padding=(10, 8), borderwidth=1, relief="solid")
            card.grid(row=0, column=col, sticky="nsew", padx=4)
            ttk.Label(card, text=title, style="CardMuted.TLabel").pack(anchor="w")
            lbl_val = tk.Label(card, text="—", font=("Segoe UI", 12, "bold"), fg="#0f172a", bg=SURFACE)
            lbl_val.pack(anchor="w", pady=(4, 0))
            self.compare_cards[key] = lbl_val

        self.compare_tabs = ttk.Notebook(self.compare_frame)
        self.compare_tabs.pack(fill="both", expand=True)

        bus_cmp_frame = ttk.Frame(self.compare_tabs, style="Card.TFrame", padding=6)
        self.compare_tabs.add(bus_cmp_frame, text="So sánh điện áp nút")
        bus_cmp_cols = [
            ("id", "Nút", 65),
            ("base_type", "Loại Base", 90),
            ("cur_type", "Loại Hiện tại", 90),
            ("base_u", "U Base (pu)", 100),
            ("cur_u", "U Hiện tại (pu)", 100),
            ("delta_u", "ΔU (pu)", 100),
            ("delta_u_pct", "ΔU (%)", 90),
            ("eval", "Đánh giá", 140)
        ]
        self.compare_bus_table = self.make_table(bus_cmp_frame, bus_cmp_cols)
        self._configure_table_tags(self.compare_bus_table)

        br_cmp_frame = ttk.Frame(self.compare_tabs, style="Card.TFrame", padding=6)
        self.compare_tabs.add(br_cmp_frame, text="So sánh mang tải nhánh")
        br_cmp_cols = [
            ("id", "Nhánh", 80),
            ("from_to", "Đoạn tuyến", 85),
            ("base_p", "Pf Base (MW)", 105),
            ("cur_p", "Pf Hiện tại (MW)", 105),
            ("base_load", "Tải Base (%)", 95),
            ("cur_load", "Tải Hiện tại (%)", 95),
            ("delta_load", "ΔTải (%)", 95),
            ("eval", "Đánh giá", 140)
        ]
        self.compare_branch_table = self.make_table(br_cmp_frame, br_cmp_cols)
        self._configure_table_tags(self.compare_branch_table)

        self.base_case_result = None

    def set_as_base_case(self):
        if not self.result:
            messagebox.showinfo("So sánh kịch bản", "Chưa có kết quả trào lưu công suất. Hãy bấm F5 để giải trước.", parent=self)
            return
        self.base_case_result = copy.deepcopy(self.result)
        name = self.result.get("name", "Kịch bản cơ sở")
        buses_count = len(self.result.get("buses", []))
        self.base_case_info.set(f"Base Case: {name} ({buses_count} nút) · Đã lưu")
        self.update_comparison()
        messagebox.showinfo("Thành công", "Đã lưu kết quả hiện tại làm Base Case!\nBây giờ bạn có thể thay đổi phụ tải, nguồn phát hoặc ngắt nhánh rồi bấm F5 để quan sát sai biệt so với Base Case.", parent=self)

    def clear_base_case(self):
        self.base_case_result = None
        self.base_case_info.set("Base Case: [Chưa lưu] (Hãy giải F5 rồi bấm nút để lưu kịch bản cơ sở)")
        for card in self.compare_cards.values():
            card.configure(text="—")
        self.compare_bus_table.delete(*self.compare_bus_table.get_children())
        self.compare_branch_table.delete(*self.compare_branch_table.get_children())

    def update_comparison(self):
        if not hasattr(self, "compare_bus_table"):
            return
        self.compare_bus_table.delete(*self.compare_bus_table.get_children())
        self.compare_branch_table.delete(*self.compare_branch_table.get_children())

        if not self.base_case_result or not self.result:
            for card in self.compare_cards.values():
                card.configure(text="—")
            return

        base = self.base_case_result
        cur = self.result

        # 1. Delta Losses
        base_ploss = base.get("total_loss_p_mw", 0.0)
        cur_ploss = cur.get("total_loss_p_mw", 0.0)
        delta_ploss = cur_ploss - base_ploss
        delta_ploss_pct = (delta_ploss / max(base_ploss, 1e-4)) * 100.0 if base_ploss > 0 else 0.0
        sign_ploss = "+" if delta_ploss >= 0 else ""
        self.compare_cards["loss_delta"].configure(
            text=f"{sign_ploss}{delta_ploss:.3f} MW ({sign_ploss}{delta_ploss_pct:.1f}%)"
        )

        # 2. Compare Buses
        base_buses = {str(b["id"]): b for b in base.get("buses", [])}
        cur_buses = {str(b["id"]): b for b in cur.get("buses", [])}
        all_bus_ids = sorted(set(base_buses.keys()) | set(cur_buses.keys()), key=lambda x: int(x) if x.isdigit() else x)

        max_delta_u = 0.0
        for i, b_id in enumerate(all_bus_ids):
            b_base = base_buses.get(b_id)
            b_cur = cur_buses.get(b_id)

            u_base = b_base["vm_pu"] if b_base else None
            u_cur = b_cur["vm_pu"] if b_cur else None

            if u_base is not None and u_cur is not None:
                delta_u = u_cur - u_base
                delta_u_pct = (delta_u / u_base) * 100.0
                if abs(delta_u) > max_delta_u:
                    max_delta_u = abs(delta_u)

                sign = "+" if delta_u >= 0 else ""
                eval_txt = "Ổn định"
                tag = "even" if i % 2 == 0 else "odd"
                if abs(delta_u) >= 0.05:
                    eval_txt = "Biến động mạnh"
                    tag = "warning"
                if u_cur < 0.95 or u_cur > 1.05:
                    eval_txt = "Vi phạm ngưỡng áp"
                    tag = "critical"

                vals = [
                    b_id,
                    b_base.get("type_final", "—"),
                    b_cur.get("type_final", "—"),
                    f"{u_base:.4f}",
                    f"{u_cur:.4f}",
                    f"{sign}{delta_u:.4f}",
                    f"{sign}{delta_u_pct:.2f}%",
                    eval_txt
                ]
            else:
                vals = [b_id, "—", "—", "—", "—", "—", "—", "Không khớp nút"]
                tag = "odd"

            self.compare_bus_table.insert("", "end", values=vals, tags=(tag,))

        self.compare_cards["volt_delta"].configure(text=f"{max_delta_u:.4f} p.u.")

        # 3. Compare Branches
        base_brs = {str(br["id"]): br for br in base.get("branches", [])}
        cur_brs = {str(br["id"]): br for br in cur.get("branches", [])}
        all_br_ids = sorted(set(base_brs.keys()) | set(cur_brs.keys()), key=lambda x: int(x) if x.isdigit() else x)

        max_delta_load = 0.0
        for j, br_id in enumerate(all_br_ids):
            br_base = base_brs.get(br_id)
            br_cur = cur_brs.get(br_id)

            if br_base and br_cur:
                from_to = f"{br_base.get('from_bus')} ➔ {br_base.get('to_bus')}"
                p_base = br_base.get("p_from_mw", 0.0)
                p_cur = br_cur.get("p_from_mw", 0.0)
                load_base = br_base.get("loading_percent")
                load_cur = br_cur.get("loading_percent")

                if load_base is not None and load_cur is not None:
                    delta_load = load_cur - load_base
                    if abs(delta_load) > max_delta_load:
                        max_delta_load = abs(delta_load)
                    sign_load = "+" if delta_load >= 0 else ""
                    load_diff_txt = f"{sign_load}{delta_load:.1f}%"
                    load_b_txt = f"{load_base:.1f}%"
                    load_c_txt = f"{load_cur:.1f}%"
                else:
                    delta_load = 0.0
                    load_diff_txt = "—"
                    load_b_txt = "—"
                    load_c_txt = "—"

                eval_br = "Bình thường"
                tag_br = "even" if j % 2 == 0 else "odd"
                if load_cur is not None and load_cur > 85.0:
                    eval_br = "Quá tải"
                    tag_br = "critical"
                elif abs(delta_load) >= 15.0:
                    eval_br = "Thay đổi lớn"
                    tag_br = "warning"

                vals_br = [
                    br_id,
                    from_to,
                    f"{p_base:.2f}",
                    f"{p_cur:.2f}",
                    load_b_txt,
                    load_c_txt,
                    load_diff_txt,
                    eval_br
                ]
            else:
                status_note = "Đã ngắt / Bỏ" if not br_cur else "Mới thêm"
                from_to = f"{(br_base or br_cur).get('from_bus')} ➔ {(br_base or br_cur).get('to_bus')}"
                vals_br = [br_id, from_to, "—", "—", "—", "—", "—", status_note]
                tag_br = "warning"

            self.compare_branch_table.insert("", "end", values=vals_br, tags=(tag_br,))

        self.compare_cards["load_delta"].configure(text=f"{max_delta_load:.1f}%")

    def _build_solvers_benchmark_tab(self):
        self.benchmark_frame = ttk.Frame(self.tabs, style="Card.TFrame", padding=14)
        self.tabs.add(self.benchmark_frame, text="⚡ So sánh 4 phương pháp")

        # 1. Top toolbar
        toolbar = ttk.Frame(self.benchmark_frame, style="Card.TFrame")
        toolbar.pack(fill="x", pady=(0, 10))

        self.btn_run_benchmark = ttk.Button(
            toolbar, text="🚀 Chạy so sánh cả 4 phương pháp", command=self.run_solvers_benchmark, style="Primary.TButton"
        )
        self.btn_run_benchmark.pack(side="left")

        self.btn_export_benchmark = ttk.Button(
            toolbar, text="Xuất bảng so sánh CSV...", command=self.export_solvers_benchmark, style="Small.TButton"
        )
        self.btn_export_benchmark.pack(side="left", padx=8)

        self.benchmark_status_var = tk.StringVar(value="Sẵn sàng chạy đồng thời cả 4 phương pháp trên dữ liệu hiện tại để so sánh đối chứng.")
        ttk.Label(toolbar, textvariable=self.benchmark_status_var, style="CardMuted.TLabel").pack(side="right", padx=6)

        # 2. Comparison cards banner: 4 methods summary
        cards_frame = ttk.Frame(self.benchmark_frame, style="Card.TFrame")
        cards_frame.pack(fill="x", pady=(0, 10))
        cards_frame.columnconfigure((0, 1, 2, 3), weight=1)

        self.bench_cards = []
        method_cards_info = [
            ("Newton-Raphson (NR)", "#0d9488", "Hội tụ bậc hai (quadratic)\n3-5 bước lặp\nJacobian 2N×2N\nChuẩn công nghiệp"),
            ("Phân tách nhanh (FDPF)", "#0284c7", "Ma trận B', B'' hằng số\nBỏ qua đạo hàm chéo\nMỗi bước cực nhanh\nLưới truyền tải R ≪ X"),
            ("Gauss-Seidel (GS)", "#d97706", "Lặp điện áp nút phức\nHội tụ tuyến tính (chậm)\nBộ nhớ tối thiểu O(N)\nGiảng dạy & Lưới nhỏ"),
            ("Trào lưu một chiều (DC)", "#7c3aed", "Tuyến tính 1 bước P=Bθ\nKhông cần lặp, ko phân kỳ\nBỏ qua R, Q, sụt áp U\nQuy hoạch & Thị trường"),
        ]
        for col, (title, color, desc) in enumerate(method_cards_info):
            card = tk.Frame(cards_frame, bg=SURFACE, padx=10, pady=8, highlightthickness=1, highlightbackground=LINE)
            card.grid(row=0, column=col, sticky="nsew", padx=4)
            self.bench_cards.append(card)

            tk.Label(card, text=title, font=("Segoe UI", 10, "bold"), fg=color, bg=SURFACE).pack(anchor="w")
            tk.Label(card, text=desc, font=("Segoe UI", 8), fg=MUTED, bg=SURFACE, justify="left").pack(anchor="w", pady=(3, 0))

        # 3. KPI Summary Table
        kpi_title_row = ttk.Frame(self.benchmark_frame, style="Card.TFrame")
        kpi_title_row.pack(fill="x", pady=(4, 4))
        ttk.Label(kpi_title_row, text="Bảng đối chiếu hiệu năng 4 phương pháp (KPI Benchmark)", style="Section.TLabel").pack(side="left")

        kpi_frame = ttk.Frame(self.benchmark_frame, style="Card.TFrame")
        kpi_frame.pack(fill="x", pady=(0, 10))
        kpi_cols = [
            ("name", "Phương pháp", 185),
            ("status", "Trạng thái", 120),
            ("iterations", "Số bước", 75),
            ("time_ms", "Thời gian (ms)", 95),
            ("max_mismatch", "Sai lệch max (pu)", 120),
            ("max_v_diff", "|ΔU| max vs NR", 115),
            ("max_ang_diff", "|Δθ| max vs NR", 115),
            ("p_loss", "Tổn thất P (MW)", 110),
            ("suitability", "Phạm vi ứng dụng tối ưu", 260)
        ]
        self.bench_kpi_table = self.make_table(kpi_frame, kpi_cols)
        self._configure_table_tags(self.bench_kpi_table)
        kpi_frame.rowconfigure(0, minsize=140)

        # 4. Detail Notebook: Bus voltages, Branch flows, Theory
        self.bench_detail_tabs = ttk.Notebook(self.benchmark_frame)
        self.bench_detail_tabs.pack(fill="both", expand=True)

        # Tab 4.1: Bus Voltages comparison
        bus_tab = ttk.Frame(self.bench_detail_tabs, style="Card.TFrame", padding=6)
        self.bench_detail_tabs.add(bus_tab, text="Chi tiết điện áp nút (NR vs FDPF vs GS vs DC)")
        bus_cols = [
            ("id", "Nút", 65),
            ("type", "Loại", 85),
            ("v_nr", "U NR (pu)", 95),
            ("ang_nr", "Góc NR (°)", 95),
            ("v_fdpf", "U FDPF (pu)", 95),
            ("ang_fdpf", "Góc FDPF (°)", 95),
            ("v_gs", "U GS (pu)", 95),
            ("ang_gs", "Góc GS (°)", 95),
            ("v_dc", "U DC (pu)", 95),
            ("ang_dc", "Góc DC (°)", 95),
        ]
        self.bench_bus_table = self.make_table(bus_tab, bus_cols)
        self._configure_table_tags(self.bench_bus_table)

        # Tab 4.2: Branch Flows comparison
        br_tab = ttk.Frame(self.bench_detail_tabs, style="Card.TFrame", padding=6)
        self.bench_detail_tabs.add(br_tab, text="Chi tiết dòng công suất nhánh P (MW)")
        br_cols = [
            ("id", "Nhánh", 75),
            ("from_to", "Đoạn tuyến", 85),
            ("p_nr", "P NR (MW)", 100),
            ("p_fdpf", "P FDPF (MW)", 100),
            ("p_gs", "P GS (MW)", 100),
            ("p_dc", "P DC (MW)", 100),
            ("diff_fdpf", "Δ P FDPF (MW)", 110),
            ("diff_dc", "Δ P DC (MW)", 110),
            ("err_dc_pct", "Sai số DC (%)", 100)
        ]
        self.bench_branch_table = self.make_table(br_tab, br_cols)
        self._configure_table_tags(self.bench_branch_table)

        # Tab 4.3: Theory & Comparison text
        theory_tab = ttk.Frame(self.bench_detail_tabs, style="Card.TFrame", padding=6)
        self.bench_detail_tabs.add(theory_tab, text="📖 Phân tích lý thuyết & Đánh giá chuyên sâu")
        self.bench_theory_text = ScrolledText(theory_tab, wrap="word", font=("Consolas", 10), state="disabled",
                                              background=SURFACE, foreground=INK, borderwidth=0, padx=8, pady=8)
        self.bench_theory_text.pack(fill="both", expand=True)
        self._populate_bench_theory()

        self.bench_results_data = None

    def run_solvers_benchmark(self):
        if not self.validate_input():
            messagebox.showerror("Dữ liệu không hợp lệ", "Vui lòng sửa các lỗi dữ liệu trước khi so sánh 4 phương pháp.", parent=self)
            return
        data = parse_case(self.text())
        tol, max_iter = self._read_options()
        enforce_q = self.enforce_q.get()

        self.btn_run_benchmark.configure(state="disabled", text="Đang giải 4 phương pháp…")
        self.benchmark_status_var.set("Đang chạy đối sánh NR, FDPF, GS và DC Flow...")
        self.update_idletasks()

        def run():
            try:
                res = benchmark_all_solvers(data, tolerance=tol, max_iterations=max_iter, enforce_q_limits=enforce_q)
                self.bench_queue.put((res, None))
            except Exception as e:
                self.bench_queue.put((None, e))

        threading.Thread(target=run, daemon=True).start()
        self._poll_benchmark()

    def _poll_benchmark(self):
        if self._closed:
            return
        try:
            res, err = self.bench_queue.get_nowait()
            self._on_solvers_benchmark_finished(res, err)
        except queue.Empty:
            self.after(50, self._poll_benchmark)

    def _on_solvers_benchmark_finished(self, res, error):
        self.btn_run_benchmark.configure(state="normal", text="🚀 Chạy so sánh cả 4 phương pháp")
        if error:
            messagebox.showerror("Lỗi so sánh bộ giải", str(error), parent=self)
            self.benchmark_status_var.set(f"Lỗi: {error}")
            return

        self.bench_results_data = res
        self.benchmark_status_var.set(f"Hoàn thành so sánh 4 phương pháp cho lưới '{res.get('case_name')}'!")

        # 1. KPI table
        self.bench_kpi_table.delete(*self.bench_kpi_table.get_children())
        for i, row in enumerate(res.get("kpi_summary", [])):
            tag = "even" if i % 2 == 0 else "odd"
            if row.get("converged"):
                if row.get("code") == "NR":
                    tag = "slack"
                elif row.get("code") == "FDPF":
                    tag = "pv"
            else:
                tag = "critical"

            mis_str = f"{row['max_mismatch_pu']:.2e}" if row.get("max_mismatch_pu") is not None else "—"
            v_diff_str = f"{row['max_v_diff_pu']:.5f}" if row.get("max_v_diff_pu") is not None else "—"
            a_diff_str = f"{row['max_ang_diff_deg']:.3f}°" if row.get("max_ang_diff_deg") is not None else "—"
            loss_str = f"{row['p_loss_mw']:.3f}" if row.get("p_loss_mw") is not None else "—"

            vals = [
                row.get("name", ""),
                row.get("status", ""),
                str(row.get("iterations", 0)),
                f"{row.get('time_ms', 0.0):.2f}",
                mis_str,
                v_diff_str,
                a_diff_str,
                loss_str,
                row.get("suitability", "")
            ]
            self.bench_kpi_table.insert("", "end", values=vals, tags=(tag,))

        # 2. Bus comparison table
        self.bench_bus_table.delete(*self.bench_bus_table.get_children())
        for i, b in enumerate(res.get("bus_comparison", [])):
            tag = "even" if i % 2 == 0 else "odd"
            vals = [
                b.get("id"),
                b.get("type"),
                b.get("v_nr"),
                b.get("ang_nr"),
                b.get("v_fdpf"),
                b.get("ang_fdpf"),
                b.get("v_gs"),
                b.get("ang_gs"),
                b.get("v_dc"),
                b.get("ang_dc"),
            ]
            self.bench_bus_table.insert("", "end", values=vals, tags=(tag,))

        # 3. Branch comparison table
        self.bench_branch_table.delete(*self.bench_branch_table.get_children())
        for j, br in enumerate(res.get("branch_comparison", [])):
            tag = "even" if j % 2 == 0 else "odd"
            p_nr = br.get("p_nr")
            p_fdpf = br.get("p_fdpf")
            p_dc = br.get("p_dc")

            diff_fdpf = round(p_fdpf - p_nr, 2) if isinstance(p_fdpf, (int, float)) and isinstance(p_nr, (int, float)) else "—"
            diff_dc = round(p_dc - p_nr, 2) if isinstance(p_dc, (int, float)) and isinstance(p_nr, (int, float)) else "—"
            err_dc_pct = f"{(abs(p_dc - p_nr) / max(abs(p_nr), 1.0) * 100.0):.1f}%" if isinstance(p_dc, (int, float)) and isinstance(p_nr, (int, float)) else "—"

            vals = [
                br.get("id"),
                br.get("from_to"),
                p_nr,
                p_fdpf,
                br.get("p_gs"),
                p_dc,
                diff_fdpf,
                diff_dc,
                err_dc_pct
            ]
            self.bench_branch_table.insert("", "end", values=vals, tags=(tag,))

    def _populate_bench_theory(self):
        text = """================================================================================
SO SÁNH BỐN PHƯƠNG PHÁP TÍNH TOÁN TRÀO LƯU CÔNG SUẤT PHỔ BIẾN
================================================================================

1. PHƯƠNG PHÁP NEWTON-RAPHSON (NR)
--------------------------------------------------------------------------------
- Bản chất toán học: Giải hệ phương trình phi tuyến AC bằng khai triển chuỗi Taylor bậc nhất,
  bỏ qua các đạo hàm bậc cao. Mỗi bước lặp giải hệ phương trình tuyến tính:
      [ ΔP ]   [ H   N ] [ Δθ ]
      [ ΔQ ] = [ M   L ] [ ΔV/V ]
  với ma trận Jacobian kích thước (2N x 2N).
- Điểm mạnh:
  + Tốc độ hội tụ bậc hai (quadratic): số chữ số có nghĩa tăng gấp đôi sau mỗi bước.
  + Số bước lặp độc lập với kích thước hệ thống (thường chỉ 3-5 bước là hội tụ).
  + Rất ổn định với lưới phức tạp, nhiều giới hạn Q, máy biến áp điều chỉnh nấc.
- Điểm yếu:
  + Khối lượng tính toán mỗi bước lớn do phải liên tục cập nhật và nghịch đảo Jacobian O(N^3).
  + Ma trận có thể suy biến nếu điểm khởi tạo quá xa hoặc lưới chịu tải cực hạn.
- Phạm vi ứng dụng: Tiêu chuẩn công nghiệp cho thiết kế, quy hoạch, vận hành thời gian thực (EMS/SCADA).

2. PHƯƠNG PHÁP PHÂN TÁCH NHANH (FAST DECOUPLED POWER FLOW - FDPF)
--------------------------------------------------------------------------------
- Bản chất toán học: Dựa trên đặc tính vật lý lưới truyền tải (X >> R):
  + Công suất tác dụng P chủ yếu phụ thuộc góc pha θ (bỏ qua N = 0).
  + Công suất phản kháng Q chủ yếu phụ thuộc biên độ điện áp V (bỏ qua M = 0).
  + Giả định V ≈ 1.0 p.u. và cos(θij) ≈ 1, thu về 2 phương trình độc lập:
      ΔP / V = B' · Δθ
      ΔQ / V = B'' · ΔV
- Điểm mạnh:
  + Hai ma trận B' và B'' là hằng số đối xứng, chỉ cần phân tích LU một lần duy nhất lúc đầu!
  + Tốc độ mỗi bước lặp nhanh gấp 4-5 lần so với NR.
  + Tiết kiệm bộ nhớ RAM đáng kể.
- Điểm yếu:
  + Mất tính chất hội tụ bậc hai (thường cần 6-10 bước lặp).
  + Kém hội tụ hoặc phân kỳ trên lưới phân phối có tỷ số R/X cao.
- Phạm vi ứng dụng: Phân tích sự cố N-1 (Contingency Analysis), giám sát an ninh động lưới truyền tải.

3. PHƯƠNG PHÁP GAUSS-SEIDEL (GS)
--------------------------------------------------------------------------------
- Bản chất toán học: Lặp điểm bất động trên phương trình điện áp nút:
      V_i^(k+1) = (1 / Y_ii) * [ (P_i - j Q_i) / conj(V_i) - Σ (Y_ij * V_j) ]
  Sử dụng ngay giá trị điện áp vừa tính của nút trước để cập nhật nút sau (Successive Displacement).
- Điểm mạnh:
  + Thuật toán cực kỳ đơn giản, không cần xây dựng hay đảo ma trận Jacobian.
  + Tiêu tốn bộ nhớ ít nhất (chỉ cần lưu mảng Ybus và vector V).
- Điểm yếu:
  + Hội tụ tuyến tính (rất chậm), số bước lặp tăng vọt theo kích thước số nút lưới (vài chục đến hàng trăm bước).
  + Rất nhạy cảm với topology: dễ phân kỳ nếu có nhánh bù nối tiếp hoặc lưới hình tia dài.
- Phạm vi ứng dụng: Mục đích giảng dạy, minh họa thuật toán, lưới điện quy mô rất nhỏ.

4. PHƯƠNG PHÁP TRÀO LƯU CÔNG SUẤT MỘT CHIỀU (DC POWER FLOW)
--------------------------------------------------------------------------------
- Bản chất toán học: Tuyến tính hóa hoàn toàn hệ phương trình trào lưu công suất:
  + Bỏ qua điện trở R = 0 (thuần kháng).
  + Giả định điện áp tại mọi nút bằng đúng 1.0 p.u. (V_i = 1.0).
  + Góc lệch pha giữa các nút rất nhỏ (sin θ_ij ≈ θ_ij, cos θ_ij ≈ 1).
  + Hệ phương trình quy về:
      P_bus = B_bus · θ
- Điểm mạnh:
  + Giải hệ phương trình đại số tuyến tính ĐÚNG 1 LẦN (Non-iterative).
  + Luôn luôn tìm được nghiệm duy nhất, 100% không bao giờ phân kỳ!
  + Tốc độ tính toán siêu nhanh.
- Điểm yếu:
  + Hoàn toàn không tính được công suất phản kháng Q và sụt áp U.
  + Sai số công suất tác dụng P thường từ 5% đến 10% so với trào lưu xoay chiều AC.
- Phạm vi ứng dụng: Bài toán thị trường điện (LMP), tối ưu hóa chi phí phát điện (OPF),
  quy hoạch dài hạn, sàng lọc nhanh sự cố trước khi chạy kiểm tra chi tiết bằng AC.
================================================================================
"""
        self.bench_theory_text.configure(state="normal")
        self.bench_theory_text.delete("1.0", "end")
        self.bench_theory_text.insert("1.0", text.strip())
        self.bench_theory_text.configure(state="disabled")

    def export_solvers_benchmark(self):
        if not self.bench_results_data:
            messagebox.showinfo("Xuất kết quả", "Chưa có kết quả so sánh để xuất. Hãy bấm 'Chạy so sánh cả 4 phương pháp' trước.", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Xuất bảng so sánh 4 phương pháp trào lưu công suất",
            defaultextension=".csv",
            filetypes=[("Bảng tính CSV", "*.csv"), ("Tất cả", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow([f"# BẢNG SO SÁNH 4 PHƯƠNG PHÁP TRÀO LƯU CÔNG SUẤT: {self.bench_results_data.get('case_name', '')}"])
                writer.writerow([])
                writer.writerow(["=== 1. TỔNG HỢP HIỆU NĂNG VÀ HỘI TỤ (KPI) ==="])
                writer.writerow(["Phương pháp", "Trạng thái", "Số bước lặp", "Thời gian (ms)", "Sai lệch max (pu)", "|ΔU| max vs NR (pu)", "|Δθ| max vs NR (°)", "Tổn thất P (MW)", "Ứng dụng"])
                for row in self.bench_results_data.get("kpi_summary", []):
                    writer.writerow([
                        row.get("name"), row.get("status"), row.get("iterations"), row.get("time_ms"),
                        row.get("max_mismatch_pu"), row.get("max_v_diff_pu"), row.get("max_ang_diff_deg"),
                        row.get("p_loss_mw"), row.get("suitability")
                    ])
                writer.writerow([])
                writer.writerow(["=== 2. SO SÁNH ĐIỆN ÁP VÀ GÓC PHA TẠI CÁC NÚT ==="])
                writer.writerow(["Nút", "Loại", "U NR (pu)", "Góc NR (°)", "U FDPF (pu)", "Góc FDPF (°)", "U GS (pu)", "Góc GS (°)", "U DC (pu)", "Góc DC (°)"])
                for b in self.bench_results_data.get("bus_comparison", []):
                    writer.writerow([b.get("id"), b.get("type"), b.get("v_nr"), b.get("ang_nr"), b.get("v_fdpf"), b.get("ang_fdpf"), b.get("v_gs"), b.get("ang_gs"), b.get("v_dc"), b.get("ang_dc")])
                writer.writerow([])
                writer.writerow(["=== 3. SO SÁNH DÒNG CÔNG SUẤT TÁC DỤNG TRÊN CÁC NHÁNH P (MW) ==="])
                writer.writerow(["Nhánh", "Đoạn tuyến", "P NR (MW)", "P FDPF (MW)", "P GS (MW)", "P DC (MW)"])
                for br in self.bench_results_data.get("branch_comparison", []):
                    writer.writerow([br.get("id"), br.get("from_to"), br.get("p_nr"), br.get("p_fdpf"), br.get("p_gs"), br.get("p_dc")])
            messagebox.showinfo("Thành công", f"Đã xuất bảng so sánh 4 phương pháp ra:\n{path}", parent=self)
        except Exception as e:
            messagebox.showerror("Lỗi xuất tệp", str(e), parent=self)

    def _build_footer(self):
        footer = ttk.Frame(self, padding=(18, 10))
        footer.pack(side="bottom", fill="x")

        self.state_badge = tk.Label(footer, textvariable=self.state_text, background="#e2e8f0", foreground=MUTED,
                                    font=("Segoe UI", 9, "bold"), padx=10, pady=5)
        self.state_badge.pack(side="left", padx=(0, 10))

        label = ttk.Label(footer, textvariable=self.status, style="Muted.TLabel", wraplength=440)
        label.pack(side="left", fill="x", expand=True)

        self.export_buttons = []
        for extension, title in (
            ("xlsx", "Xuất Excel (4 sheet)…"),
            ("csv", "Xuất CSV…"),
            ("json", "Xuất JSON…"),
            ("txt", "Xuất báo cáo…")
        ):
            button = ttk.Button(footer, text=title, command=lambda ext=extension: self.export(ext), state="disabled")
            button.pack(side="right", padx=(6, 0))
            self.export_buttons.append(button)

        footer.bind("<Configure>", lambda event: label.configure(wraplength=max(160, event.width - 550)))

    @staticmethod
    def _shortcut(command):
        command()
        return "break"

    def text(self):
        return self.editor.get("1.0", "end-1c")

    def signature(self):
        return (self.text(), self.tolerance.get(), self.max_iter.get(), self.enforce_q.get(), self.solver_method.get())

    def _set_state(self, text, tone="idle"):
        self._current_tone = tone
        if self.theme_mode == "dark":
            colors = {
                "idle": ("#334155", "#94a3b8"),
                "busy": ("#134e4a", "#2dd4bf"),
                "success": ("#064e3b", "#4ade80"),
                "warning": ("#451a03", "#fbbf24"),
                "error": ("#450a0a", "#f87171")
            }
        else:
            colors = {
                "idle": ("#e2e8f0", "#64748b"),
                "busy": ("#ccfbf1", "#0d9488"),
                "success": ("#dcfce7", "#15803d"),
                "warning": ("#fef3c7", "#b45309"),
                "error": ("#fee2e2", "#dc2626")
            }
        bg, fg = colors.get(tone, colors["idle"])
        self.state_text.set(text)
        self.state_badge.configure(background=bg, foreground=fg)
        if hasattr(self, "header_status_dot"):
            dot_labels = {
                "idle": ("● Sẵn sàng", "#10b981"),
                "busy": ("◐ Đang tính…", "#38bdf8"),
                "success": ("● Đã hội tụ", "#10b981"),
                "warning": ("▲ Cảnh báo vi phạm", "#f59e0b"),
                "error": ("✖ Chưa hội tụ", "#ef4444")
            }
            lbl_txt, lbl_color = dot_labels.get(tone, ("● Sẵn sàng", "#10b981"))
            self.header_status_dot.configure(text=lbl_txt, fg=lbl_color)

    def set_report(self, text):
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        self.report.insert("1.0", text)
        self.report.configure(state="disabled")

    def invalidate(self):
        self.result = self.result_source = None
        for kind in self.tables:
            self.table_rows[kind] = []
            self.render_table(kind)
        for button in self.export_buttons:
            button.configure(state="disabled")
        self.dashboard.clear("Chọn dữ liệu và thiết lập bộ giải.\nBấm Tính toán trào lưu hoặc F5 để xem kết quả.")
        if hasattr(self, "diagram"):
            self.diagram.clear()
        if hasattr(self, "update_comparison"):
            self.update_comparison()
        if hasattr(self, "bench_kpi_table"):
            self.bench_kpi_table.delete(*self.bench_kpi_table.get_children())
            self.bench_bus_table.delete(*self.bench_bus_table.get_children())
            self.bench_branch_table.delete(*self.bench_branch_table.get_children())
            self.benchmark_status_var.set("Dữ liệu đã đổi · Bấm 'Chạy so sánh cả 4 phương pháp' để cập nhật.")
        self.set_report("Chưa có báo cáo cho dữ liệu hiện tại.\n\n1. Mở tệp JSON/Excel hoặc chọn lưới mẫu.\n2. Kiểm tra dữ liệu và thiết lập bộ giải.\n3. Bấm Tính toán trào lưu (F5).\n\nKhi hội tụ, bạn có thể xem và xuất báo cáo tại đây.")
        self._set_state("ĐANG TÍNH" if self.is_running else "CHỜ TÍNH TOÁN", "busy" if self.is_running else "idle")
        self.status.set("Dữ liệu đã đổi — cần tính lại" if not self.is_running else "Đang giải; thay đổi đầu vào sẽ cần tính lại")

    def _options_changed(self, *_):
        self.invalidate()
        self._schedule_validation()

    def _update_filename(self):
        dirty = self.text() != self.saved_text
        name = self.input_path.name if self.input_path else "Dữ liệu mới"
        self.file_label.set(f"{'● ' if dirty else ''}{name}" + (" · Chưa lưu" if dirty else ""))
        self.title(f"{'* ' if dirty else ''}{name} — PowerFlow")

    def on_edit(self, _event=None):
        if self.editor.edit_modified():
            self.editor.edit_modified(False)
            self.invalidate()
            self._update_filename()
            self._schedule_validation()

    def _schedule_validation(self):
        if self._validation_after:
            self.after_cancel(self._validation_after)
        self._validation_after = self.after(350, self._validate_later)

    def _validate_later(self):
        self._validation_after = None
        self.validate_input()

    def _read_options(self):
        self.tolerance_entry.state(["!invalid"])
        self.iteration_entry.state(["!invalid"])
        try:
            tol = float(self.tolerance.get())
            if not math.isfinite(tol) or tol <= 0:
                raise ValueError
        except ValueError:
            self.tolerance_entry.state(["invalid"])
            raise CaseError("Dung sai phải là số hữu hạn lớn hơn 0, ví dụ 1e-8.") from None
        try:
            iterations = int(self.max_iter.get())
            if iterations < 1:
                raise ValueError
        except ValueError:
            self.iteration_entry.state(["invalid"])
            raise CaseError("Số bước tối đa mỗi lượt phải là số nguyên từ 1 trở lên.") from None
        return tol, iterations

    def _input_error(self, exc):
        self.input_feedback.set(str(exc))
        theme = THEMES[self.theme_mode]
        self.feedback_label.configure(foreground=theme["red"])
        self.case_info.set("Cần kiểm tra lại dữ liệu hoặc thiết lập bên dưới")
        self.editor.tag_remove("json_error", "1.0", "end")
        cause = exc.__cause__
        if isinstance(cause, json.JSONDecodeError):
            line = str(cause.lineno)
            err_bg = "#450a0a" if self.theme_mode == "dark" else "#fee2e2"
            self.editor.tag_configure("json_error", background=err_bg)
            self.editor.tag_add("json_error", f"{line}.0", f"{line}.end")

    def validate_input(self):
        try:
            network = validate_case(parse_case(self.text()))
            self._read_options()
        except (CaseError, ValueError) as exc:
            self._input_error(exc)
            return False
        self.editor.tag_remove("json_error", "1.0", "end")
        self.case_info.set(f"{network.name}\n{len(network.buses)} nút  ·  {len(network.branches)} nhánh  ·  {network.base_mva:g} MVA")
        self.input_feedback.set("✓ Dữ liệu và thiết lập hợp lệ")
        theme = THEMES[self.theme_mode]
        self.feedback_label.configure(foreground=theme["teal"])
        return True

    def replace_editor(self, text, path):
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", text)
        self.editor.mark_set("insert", "1.0")
        self.editor.see("1.0")
        self.editor.edit_reset()
        self.editor.edit_modified(False)
        self.saved_text = text
        self.input_path = Path(path) if path else None
        self._update_filename()
        self.json_editor.refresh()
        try:
            parsed = parse_case(text)
            self._syncing_editor = True
            if hasattr(self, "table_editor"):
                self.table_editor.set_case_data(parsed)
        except Exception:
            pass
        finally:
            self._syncing_editor = False
        self.invalidate()
        self.validate_input()

    def confirm_discard(self):
        if self.text() == self.saved_text:
            return True
        answer = messagebox.askyesnocancel("Lưu thay đổi?", "Dữ liệu có thay đổi chưa lưu.\nBạn có muốn lưu trước khi tiếp tục?", parent=self)
        if answer is None:
            return False
        return self.save_case() if answer else True

    def load_example(self, filename, confirm=True):
        path = ROOT / "examples" / filename
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            messagebox.showerror("Không mở được ví dụ", str(exc), parent=self)
            return
        if confirm and not self.confirm_discard():
            return
        self.replace_editor(content, path)
        for label, name in EXAMPLES.items():
            if name == filename:
                self.example.set(label)
        self.status.set("Đã nạp lưới mẫu · Bấm F5 để tính toán")

    def open_case(self):
        if not self.confirm_discard():
            return
        name = filedialog.askopenfilename(
            parent=self,
            filetypes=[
                ("Tất cả định dạng hỗ trợ", "*.json;*.xlsx;*.csv"),
                ("Dữ liệu JSON", "*.json"),
                ("Bảng tính Excel", "*.xlsx"),
                ("Bảng tính CSV", "*.csv"),
                ("Tất cả", "*.*")
            ]
        )
        if not name:
            return
        try:
            path = Path(name)
            ext = path.suffix.lower()
            if ext == ".xlsx":
                case_data = load_from_excel(path)
                content = json.dumps(case_data, ensure_ascii=False, indent=2) + "\n"
            elif ext == ".csv":
                case_data = load_from_csv(path)
                content = json.dumps(case_data, ensure_ascii=False, indent=2) + "\n"
            else:
                content = path.read_text(encoding="utf-8-sig")
            self.replace_editor(content, path)
            self.status.set(f"Đã mở {path.name} · Kiểm tra thông báo trước khi tính")
        except (CaseError, OSError, UnicodeError) as exc:
            messagebox.showerror("Không mở được dữ liệu", str(exc), parent=self)

    def save_case(self):
        content = self.text()
        try:
            data = parse_case(content)
        except CaseError as exc:
            self._input_error(exc)
            self.status.set("Chưa lưu — hãy sửa lỗi JSON")
            return False
        initial = self.input_path.name if self.input_path and self.input_path.parent != ROOT / "examples" else "luoi_cua_ban.json"
        name = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".json",
            initialfile=initial,
            filetypes=[("Dữ liệu JSON", "*.json"), ("Bảng tính Excel", "*.xlsx")]
        )
        if not name:
            return False
        try:
            path = Path(name)
            if path.suffix.lower() == ".xlsx":
                export_case_to_excel(data, path)
            else:
                path.write_text(content, encoding="utf-8")
        except (CaseError, OSError, UnicodeError) as exc:
            messagebox.showerror("Không lưu được dữ liệu", str(exc), parent=self)
            return False
        self.input_path, self.saved_text = Path(name), content
        self._update_filename()
        self.status.set(f"Đã lưu {Path(name).name}")
        return True

    def export_excel_template(self):
        name = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".xlsx",
            initialfile="luoi_dien_mau.xlsx",
            filetypes=[("Bảng tính Excel", "*.xlsx")]
        )
        if not name:
            return
        try:
            create_sample_excel_template(name)
            self.status.set(f"Đã tạo file Excel mẫu: {Path(name).name}")
            messagebox.showinfo("Thành công", f"Đã xuất file Excel mẫu ra:\n{name}\n\nBạn có thể mở bằng Excel để điền số đề bài!", parent=self)
        except Exception as exc:
            messagebox.showerror("Lỗi", str(exc), parent=self)

    def format_json(self):
        try:
            data = parse_case(self.text())
        except CaseError as exc:
            self._input_error(exc)
            return False
        formatted = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if formatted != self.text():
            self.editor.edit_separator()
            self.editor.delete("1.0", "end")
            self.editor.insert("1.0", formatted)
            self.editor.edit_separator()
            self.on_edit()
        self.json_editor.refresh()
        self.validate_input()
        self.status.set("Đã định dạng JSON · Ctrl+Z để hoàn tác")
        return True

    def calculate(self):
        if self.is_running:
            return
        self.invalidate()
        if not self.validate_input():
            self._set_state("CẦN KIỂM TRA", "error")
            self.status.set("Chưa tính — xem lỗi ở khung dữ liệu")
            return
        snapshot = self.signature()
        data = parse_case(snapshot[0])
        network = validate_case(data)
        tol, max_iter = self._read_options()
        self._job_limits = {bus.id: (bus.vmin_pu, bus.vmax_pu) for bus in network.buses}
        self.is_running = True
        self.run_button.configure(state="disabled", text="Đang tính toán…")
        self.progress.start(12)
        self._set_state("ĐANG TÍNH", "busy")

        method_label = self.solver_method.get()
        method_code = dict(SOLVER_METHODS).get(method_label, "NR")
        self.status.set(f"Đang giải bằng {method_label}…")
        self.dashboard.clear(f"Đang tính toán bằng {method_label}…\nKết quả sẽ hiển thị khi bộ giải hoàn tất.")
        self.tabs.select(self.dashboard)
        self._calc_start_time = time.perf_counter()

        def run():
            try:
                result = solve_power_flow(data, tolerance=tol, max_iterations=max_iter,
                                          enforce_q_limits=snapshot[3], method=method_code)
                self.worker_queue.put((snapshot, result, None))
            except Exception as exc:
                self.worker_queue.put((snapshot, None, exc))

        threading.Thread(target=run, daemon=True).start()
        self._poll_after = self.after(80, self.poll_result)

    def poll_result(self):
        if self._closed:
            return
        if self._poll_after:
            self.after_cancel(self._poll_after)
            self._poll_after = None
        try:
            snapshot, result, error = self.worker_queue.get_nowait()
        except queue.Empty:
            self._poll_after = self.after(80, self.poll_result)
            return

        elapsed_ms = (time.perf_counter() - getattr(self, "_calc_start_time", time.perf_counter())) * 1000
        self.is_running = False
        self.progress.stop()
        self.run_button.configure(state="normal", text="⚡ Tính toán trào lưu     F5")

        if self.signature() != snapshot:
            self.invalidate()
            self.status.set("Dữ liệu đã đổi trong lúc giải — bấm F5 để tính lại")
            return
        if error is not None:
            self.dashboard.show_error(str(error))
            self.set_report(f"KHÔNG CÓ KẾT QUẢ HỘI TỤ\n\n{error}")
            self._set_state("CHƯA HỘI TỤ", "error")
            self.status.set("Không tính được · Xem chi tiết trong Tổng quan")
            return

        self.result, self.result_source = result, snapshot
        self.dashboard.show_result(result, voltage_limits=self._job_limits)
        if hasattr(self, "diagram"):
            self.diagram.set_result(result)
        self.set_report(format_report(result))

        for kind in self.tables:
            self.table_rows[kind] = result[kind]
            self.render_table(kind)

        for button in self.export_buttons:
            button.configure(state="normal")

        if hasattr(self, "update_comparison"):
            self.update_comparison()

        warnings = len(result["warnings"])
        self._set_state("HỘI TỤ · CẢNH BÁO" if warnings else "ĐÃ HỘI TỤ", "warning" if warnings else "success")
        method_name = result.get("solver_method", "Newton-Raphson")
        mis_val = result.get("max_mismatch_pu")
        mis_txt = f"{mis_val:.2e} p.u." if mis_val is not None else "0.0 p.u. (DC)"
        self.status.set(f"[{method_name}] {elapsed_ms:.1f} ms · {result['iterations']} bước · Sai lệch {mis_txt} · {warnings} cảnh báo")

    @staticmethod
    def format_value(value):
        if value is None:
            return "—"
        if isinstance(value, bool):
            return "Có" if value else "Không"
        return f"{value:.5f}" if isinstance(value, float) else str(value)

    def sort_table(self, kind, key):
        previous, descending = self.table_sorts[kind]
        self.table_sorts[kind] = (key, not descending if previous == key else False)
        self.render_table(kind)

    def render_table(self, kind):
        tree = self.tables[kind]
        tree.delete(*tree.get_children())
        rows = self.table_rows[kind]
        query = self.filter_vars[kind].get().strip().casefold()
        visible = [row for row in rows if not query or query in " ".join(self.format_value(row[col]) for col in tree["columns"]).casefold()]
        key, descending = self.table_sorts[kind]
        if key:
            known = [row for row in visible if row[key] is not None]
            missing = [row for row in visible if row[key] is None]
            known.sort(key=lambda row: row[key].casefold() if isinstance(row[key], str) else row[key], reverse=descending)
            visible = known + missing

        for col, label, _width in (BUS_COLUMNS if kind == "buses" else BRANCH_COLUMNS):
            tree.heading(col, text=label + ((" ▼" if descending else " ▲") if col == key else ""))

        warnings = self.result["warnings"] if self.result else []
        for index, row in enumerate(visible):
            prefix = f"{'Nút' if kind == 'buses' else 'Nhánh'} {row['id']}:"
            tag = "even" if index % 2 == 0 else "odd"
            if kind == "buses":
                b_type = row.get("type_final", "")
                if b_type == "SLACK":
                    tag = "slack"
                elif "PV" in b_type:
                    tag = "pv"
                if row["type_input"] != row["type_final"]:
                    tag = "switched"
            elif kind == "branches":
                load = row.get("loading_percent")
                if load is not None:
                    if load > 85.0:
                        tag = "overload"
                    elif load >= 60.0:
                        tag = "heavy"

            if any(warning.startswith(prefix) for warning in warnings):
                tag = "warning"
            tree.insert("", "end", values=[self.format_value(row[col]) for col in tree["columns"]], tags=(tag,))

        count = f"{len(visible)} / {len(rows)} dòng"
        if rows and not visible:
            count += " · Không có dòng khớp bộ lọc"
        self.table_counts[kind].set(count if rows else "Chưa có kết quả · Bấm F5 để tính toán")

    def copy_table(self, kind):
        tree = self.tables[kind]
        selected = tree.selection()
        if not selected:
            self.status.set("Chọn một hoặc nhiều dòng trong bảng để sao chép")
            return
        lines = ["\t".join(tree.heading(key, "text").rstrip(" ▲▼") for key in tree["columns"])]
        lines += ["\t".join(map(str, tree.item(item, "values"))) for item in selected]
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))
        self.status.set(f"Đã sao chép {len(selected)} dòng · Có thể dán vào Excel")

    def copy_report(self):
        if self.result is None or self.signature() != self.result_source:
            self.status.set("Hãy tính toán thành công trước khi sao chép báo cáo")
            return
        self.clipboard_clear()
        self.clipboard_append(format_report(self.result))
        self.status.set("Đã sao chép báo cáo")

    def export(self, extension):
        if self.result is None or self.signature() != self.result_source:
            self.status.set("Hãy tính toán thành công dữ liệu hiện tại trước khi xuất")
            return

        if extension == "xlsx":
            name = filedialog.asksaveasfilename(
                parent=self,
                title="Xuất báo cáo Excel 4 sheets",
                defaultextension=".xlsx",
                initialfile="ket_qua_trao_luu.xlsx",
                filetypes=[("Bảng tính Excel 4 sheets", "*.xlsx"), ("Tất cả", "*.*")]
            )
            if not name:
                return
            try:
                export_full_results_to_excel(self.result, name)
                self.status.set(f"Đã xuất báo cáo Excel đầy đủ: {Path(name).name}")
                messagebox.showinfo("Thành công", f"Đã xuất báo cáo Excel (4 sheets) thành công:\n{name}", parent=self)
            except Exception as exc:
                messagebox.showerror("Không xuất được Excel", str(exc), parent=self)
            return

        if extension == "csv":
            name = filedialog.asksaveasfilename(parent=self, defaultextension=".csv", initialfile="ket_qua_trao_luu.csv",
                                                filetypes=[("Bảng tính CSV", "*.csv")])
            if not name:
                return
            try:
                with open(name, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.writer(f)
                    writer.writerow([f"# KẾT QUẢ TRÀO LƯU CÔNG SUẤT: {self.result.get('name', '')}"])
                    writer.writerow([f"# Cơ sở: {self.result.get('base_mva', 100)} MVA | Số bước: {self.result.get('iterations')}"])
                    writer.writerow([])
                    writer.writerow(["=== BẢNG ĐIỆN ÁP VÀ CÔNG SUẤT NÚT ==="])
                    writer.writerow([title for _, title, _ in BUS_COLUMNS])
                    for row in self.result["buses"]:
                        writer.writerow([self.format_value(row[col]) for col, _, _ in BUS_COLUMNS])
                    writer.writerow([])
                    writer.writerow(["=== BẢNG CÔNG SUẤT VÀ TỔN THẤT NHÁNH ==="])
                    writer.writerow([title for _, title, _ in BRANCH_COLUMNS])
                    for row in self.result["branches"]:
                        writer.writerow([self.format_value(row[col]) for col, _, _ in BRANCH_COLUMNS])
                self.status.set(f"Đã xuất {Path(name).name}")
            except (OSError, UnicodeError) as exc:
                messagebox.showerror("Không xuất được CSV", str(exc), parent=self)
            return

        name = filedialog.asksaveasfilename(parent=self, defaultextension=f".{extension}", initialfile=f"ket_qua.{extension}",
                                            filetypes=[("Kết quả", f"*.{extension}")])
        if not name:
            return
        try:
            if self.input_path and Path(name).resolve() == self.input_path.resolve():
                raise CaseError("Chọn tên khác để không ghi đè dữ liệu đầu vào.")
            content = (json.dumps(self.result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
                       if extension == "json" else format_report(self.result))
            Path(name).write_text(content, encoding="utf-8")
            self.status.set(f"Đã xuất {Path(name).name}")
        except (CaseError, OSError, UnicodeError) as exc:
            messagebox.showerror("Không xuất được kết quả", str(exc), parent=self)

    def show_help(self):
        window = tk.Toplevel(self)
        window.title("Hướng dẫn sử dụng · PowerFlow")
        window.geometry("880x690")
        theme = THEMES[self.theme_mode]
        window.configure(background=theme["bg"])
        window.transient(self)

        ttk.Label(window, text="Hướng dẫn sử dụng", font=("Segoe UI", 19, "bold")).pack(anchor="w", padx=22, pady=(18, 4))
        ttk.Label(window, text="F5  Tính toán  ·  Ctrl+O  Mở  ·  Ctrl+S  Lưu  ·  Ctrl+Shift+F  Định dạng  ·  Ctrl+T  Đổi giao diện",
                  style="Muted.TLabel").pack(anchor="w", padx=22, pady=(0, 12))

        text = ScrolledText(window, wrap="word", font=("Segoe UI", 11), background=theme["surface"],
                            foreground=theme["ink"], borderwidth=0, padx=16, pady=16)
        text.pack(fill="both", expand=True, padx=22, pady=(0, 18))
        try:
            content = (ROOT / "HUONG_DAN.md").read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            content = "Mở HUONG_DAN.md trong thư mục chương trình."
        text.insert("1.0", content)
        text.configure(state="disabled")
        window.bind("<Escape>", lambda _event: window.destroy())

    def close(self):
        if self.confirm_discard():
            self.destroy()

    def destroy(self):
        self._closed = True
        for callback in (self._validation_after, self._poll_after):
            if callback:
                self.after_cancel(callback)
        self.progress.stop()
        super().destroy()


def enable_high_dpi():
    """Kích hoạt chế độ nét cao High-DPI trên Windows để khắc phục hiện tượng mờ / vỡ nét."""
    import sys
    if sys.platform.startswith("win"):
        try:
            import ctypes
            # Per-Monitor V2 DPI Awareness (Windows 10 1703+)
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                # System DPI Awareness (Windows 8.1+)
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                try:
                    # Windows Vista / 7
                    ctypes.windll.user32.SetProcessDPIAware()
                except Exception:
                    pass


if __name__ == "__main__":
    enable_high_dpi()
    PowerFlowApp().mainloop()
