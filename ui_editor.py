"""A small, native Tk JSON editor with line numbers and syntax colouring."""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk


_JSON_TOKEN = re.compile(
    r'(?P<string>"(?:[^"\\]|\\.)*")'
    r'|(?P<number>(?<![\w.])-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)'
    r'|(?P<literal>\b(?:true|false|null)\b)'
)


class JsonEditor(ttk.Frame):
    """Expose ``text`` for editing and ``cursor`` for a status-bar label.

    Call :meth:`refresh` after replacing the contents programmatically. The
    editor deliberately leaves ``<<Modified>>`` available to its host.
    """

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.cursor = tk.StringVar(self, value="Dòng 1 · Cột 1")
        self._highlight_job = None
        self._redraw_job = None
        self._closed = False
        self.theme_mode = "light"
        self._font = tkfont.Font(self, family="Consolas", size=11)

        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self._panel = tk.Frame(self, background="#dce3ec", borderwidth=0)
        self._panel.grid(row=0, column=0, sticky="nsew")
        self._panel.rowconfigure(0, weight=1)
        self._panel.columnconfigure(1, weight=1)
        self._gutter = tk.Canvas(
            self._panel, width=46, background="#f3f6fa", borderwidth=0,
            highlightthickness=0, takefocus=False,
        )
        self._gutter.grid(row=0, column=0, sticky="ns", padx=(1, 0), pady=1)
        self.text = tk.Text(
            self._panel, wrap="none", undo=True, autoseparators=True, maxundo=200,
            font=self._font, width=40, height=12, background="#fbfcfe",
            foreground="#142b45", insertbackground="#147d73",
            selectbackground="#d5eae7", selectforeground="#142b45",
            inactiveselectbackground="#e5edf5", borderwidth=0,
            highlightthickness=0, padx=12, pady=10,
            tabs=(self._font.measure("  "),),
        )
        self.text.grid(row=0, column=1, sticky="nsew", padx=(0, 1), pady=1)
        self._vertical = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self._vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.text.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.text.configure(yscrollcommand=self._on_scroll, xscrollcommand=horizontal.set)
        for tag, color in (
            ("json_key", "#147d73"), ("json_string", "#586ab5"),
            ("json_number", "#b56b18"), ("json_literal", "#995ba0"),
        ):
            self.text.tag_configure(tag, foreground=color)
        self.text.tag_raise("sel")

        for sequence in ("<KeyRelease>", "<ButtonRelease-1>", "<FocusIn>"):
            self.text.bind(sequence, self.refresh, add="+")
        self.text.bind("<Configure>", self._queue_redraw, add="+")
        self._gutter.bind("<Configure>", self._queue_redraw, add="+")
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self._gutter.bind(sequence, self._gutter_scroll)
        self.text.bind("<Control-a>", self._select_all)
        self.text.bind("<Control-A>", self._select_all)
        self.text.bind("<Tab>", self._indent)
        self.text.bind("<Control-z>", lambda event: self._history("undo"))
        self.text.bind("<Control-y>", lambda event: self._history("redo"))
        self.text.bind("<Control-Shift-Z>", lambda event: self._history("redo"))

        self._menu = tk.Menu(self, tearoff=False)
        for label, virtual_event in (
            ("Cắt", "<<Cut>>"), ("Sao chép", "<<Copy>>"), ("Dán", "<<Paste>>"),
        ):
            self._menu.add_command(
                label=label, command=lambda event=virtual_event: self._clipboard(event),
            )
        self._menu.add_separator()
        self._menu.add_command(label="Chọn tất cả", command=self._select_all)
        self.text.bind("<Button-3>", self._show_menu)
        self.text.bind("<Shift-F10>", self._show_menu)
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.refresh()

    def apply_theme(self, theme_mode: str):
        self.theme_mode = theme_mode
        if theme_mode == "dark":
            self._panel.configure(background="#334155")
            self._gutter.configure(background="#0f172a")
            self.text.configure(
                background="#1e293b", foreground="#f8fafc",
                insertbackground="#38bdf8", selectbackground="#0369a1",
                selectforeground="#f8fafc", inactiveselectbackground="#334155"
            )
            for tag, color in (
                ("json_key", "#38bdf8"), ("json_string", "#818cf8"),
                ("json_number", "#fbbf24"), ("json_literal", "#c084fc"),
            ):
                self.text.tag_configure(tag, foreground=color)
        else:
            self._panel.configure(background="#dce3ec")
            self._gutter.configure(background="#f3f6fa")
            self.text.configure(
                background="#fbfcfe", foreground="#142b45",
                insertbackground="#147d73", selectbackground="#d5eae7",
                selectforeground="#142b45", inactiveselectbackground="#e5edf5"
            )
            for tag, color in (
                ("json_key", "#147d73"), ("json_string", "#586ab5"),
                ("json_number", "#b56b18"), ("json_literal", "#995ba0"),
            ):
                self.text.tag_configure(tag, foreground=color)
        self.refresh()

    def refresh(self, event=None):
        """Refresh line numbers, caret position, and debounced highlighting."""
        if self._closed:
            return
        self._queue_redraw()
        if self._highlight_job is not None:
            self.after_cancel(self._highlight_job)
        self._highlight_job = self.after(150, self._highlight)

    def _queue_redraw(self, event=None):
        if not self._closed and self._redraw_job is None:
            self._redraw_job = self.after_idle(self._redraw)

    def _on_scroll(self, first, last):
        self._vertical.set(first, last)
        self._queue_redraw()

    def _redraw(self):
        self._redraw_job = None
        if self._closed:
            return
        row, column = self.text.index("insert").split(".")
        self.cursor.set(f"Dòng {row} · Cột {int(column) + 1}")
        last_line = self.text.index("end-1c").split(".")[0]
        width = max(46, self._font.measure(last_line) + 24)
        if int(self._gutter.cget("width")) != width:
            self._gutter.configure(width=width)
        self._gutter.delete("all")
        border_col = "#334155" if self.theme_mode == "dark" else "#e4eaf1"
        self._gutter.create_line(
            width - 1, 0, width - 1, self._gutter.winfo_height(), fill=border_col,
        )
        index = self.text.index("@0,0")
        active_col = "#38bdf8" if self.theme_mode == "dark" else "#147d73"
        normal_col = "#64748b" if self.theme_mode == "dark" else "#95a2b4"
        while True:
            info = self.text.dlineinfo(index)
            if info is None:
                break
            number = index.split(".")[0]
            self._gutter.create_text(
                width - 12, info[1], text=number, anchor="ne", font=self._font,
                fill=active_col if number == row else normal_col,
            )
            index = self.text.index(f"{index}+1line")

    def _highlight(self):
        self._highlight_job = None
        if self._closed:
            return
        for tag in ("json_key", "json_string", "json_number", "json_literal"):
            self.text.tag_remove(tag, "1.0", "end")
        size = self.text.count("1.0", "end-1c", "chars")
        if size and size[0] > 200_000:
            return
        content = self.text.get("1.0", "end-1c")
        ranges = {tag: [] for tag in ("key", "string", "number", "literal")}
        for match in _JSON_TOKEN.finditer(content):
            kind = match.lastgroup
            if kind == "string":
                following = match.end()
                while following < len(content) and content[following].isspace():
                    following += 1
                if following < len(content) and content[following] == ":":
                    kind = "key"
            ranges[kind].extend((f"1.0+{match.start()}c", f"1.0+{match.end()}c"))
        for kind, indices in ranges.items():
            # Keep individual Tcl commands modest even for large pasted cases.
            for offset in range(0, len(indices), 500):
                self.text.tag_add(f"json_{kind}", *indices[offset:offset + 500])

    def _select_all(self, event=None):
        self.text.tag_add("sel", "1.0", "end-1c")
        self.text.mark_set("insert", "end-1c")
        self.text.focus_set()
        self._queue_redraw()
        return "break"

    def _indent(self, event=None):
        if self.text.tag_ranges("sel"):
            self.text.delete("sel.first", "sel.last")
        self.text.insert("insert", "  ")
        self.text.see("insert")
        self.refresh()
        return "break"

    def _history(self, operation):
        try:
            getattr(self.text, f"edit_{operation}")()
        except tk.TclError:
            pass
        self.refresh()
        return "break"

    def _clipboard(self, virtual_event):
        self.text.event_generate(virtual_event)
        self.refresh()

    def _show_menu(self, event):
        self.text.focus_set()
        if event.type == tk.EventType.KeyPress:
            bounds = self.text.bbox("insert")
            x, y = (bounds[0], bounds[1] + bounds[3]) if bounds else (12, 12)
            x += self.text.winfo_rootx()
            y += self.text.winfo_rooty()
        else:
            x, y = event.x_root, event.y_root
        try:
            self._menu.tk_popup(x, y)
        finally:
            self._menu.grab_release()
        return "break"

    def _gutter_scroll(self, event):
        if event.num == 4:
            units = -3
        elif event.num == 5:
            units = 3
        else:
            units = -int(event.delta / 120) or (-1 if event.delta > 0 else 1)
        self.text.yview_scroll(units, "units")
        return "break"

    def _on_destroy(self, event):
        if event.widget is not self:
            return
        self._closed = True
        for job in (self._highlight_job, self._redraw_job):
            if job is not None:
                self.after_cancel(job)
        self._highlight_job = self._redraw_job = None
