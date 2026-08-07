"""CYD Deck Editor - single-file Windows configuration application.

Install once:  py -m pip install customtkinter tkinterdnd2
"""

from __future__ import annotations
import copy, ctypes, json, subprocess, sys, uuid, zipfile
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import customtkinter as ctk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:
    DND_FILES = TkinterDnD = None

APP_DIR = Path.home() / "CYDDeck"

# Only types the firmware actually handles. Extend this list as you implement more.
TYPES = [
    "Application",
    "Website",
    "Keyboard Shortcut",
    "Open File",
    "Open Folder",
    "Folder",
]


def button(name="New Button"):
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "type": "Application",
        "action": "",
        "icon": "",
        "toggle": False,
        "toggleName": "",
        "toggleAction": "",
        "folder": "",
    }


def project():
    return {
        "version": 1,
        "deviceName": "CYD Deck",
        "theme": "Dark",
        "brightness": 180,
        "wallpaper": "",
        "profiles": [
            {
                "id": "default",
                "name": "Default",
                "pages": [{"name": "Home", "wallpaper": "", "buttons": []}],
            }
        ],
        "activeProfile": 0,
    }


_MODIFIER_NAMES = {
    "Control_L": "Ctrl",
    "Control_R": "Ctrl",
    "Shift_L": "Shift",
    "Shift_R": "Shift",
    "Alt_L": "Alt",
    "Alt_R": "Alt",
    "Super_L": "Win",
    "Super_R": "Win",
    "Win_L": "Win",
    "Win_R": "Win",
    "Meta_L": "Win",
    "Meta_R": "Win",
}

_KEY_DISPLAY_NAMES = {
    "Return": "Enter",
    "space": "Space",
    "BackSpace": "Backspace",
    "Prior": "PgUp",
    "Next": "PgDn",
    "Caps_Lock": "CapsLock",
    "Num_Lock": "NumLock",
    "Scroll_Lock": "ScrollLock",
    "Print": "PrintScreen",
    "KP_0": "Numpad0",
    "KP_1": "Numpad1",
    "KP_2": "Numpad2",
    "KP_3": "Numpad3",
    "KP_4": "Numpad4",
    "KP_5": "Numpad5",
    "KP_6": "Numpad6",
    "KP_7": "Numpad7",
    "KP_8": "Numpad8",
    "KP_9": "Numpad9",
    "KP_Add": "Numpad+",
    "KP_Subtract": "Numpad-",
    "KP_Multiply": "Numpad*",
    "KP_Divide": "Numpad/",
    "KP_Decimal": "Numpad.",
    "KP_Enter": "NumpadEnter",
}


class _ShortcutRecorderState:
    """Mutable state bag for the shortcut recorder dialog."""

    def __init__(self):
        self.values: list[str] = []
        self.finish_armed = False
        self.active: list[str] = []
        self.modifier_used: set[str] = set()


class _ShortcutHandlers:
    """Key event handlers for the shortcut recorder dialog."""

    def __init__(
        self, state: _ShortcutRecorderState, status_label, button_data, editor, win
    ):
        self._state = state
        self._status = status_label
        self._btn = button_data
        self._editor = editor
        self._win = win

    def _add_value(self, value: str) -> None:
        self._state.values.append(value)
        self._status.configure(
            text="Recorded: "
            + ", ".join(self._state.values)
            + "\nPress Esc, then Tab, to save it."
        )

    def _display_name(self, event) -> str:
        key = _KEY_DISPLAY_NAMES.get(
            event.keysym,
            event.keysym.upper() if len(event.keysym) == 1 else event.keysym,
        )
        parts = list(self._state.active)
        if event.state & 0x0004 and "Ctrl" not in parts:
            parts.append("Ctrl")
        if event.state & 0x0001 and "Shift" not in parts:
            parts.append("Shift")
        if event.state & 0x0008 and "Alt" not in parts:
            parts.append("Alt")
        return "+".join(parts + [key])

    def _finish(self) -> None:
        value = ", ".join(self._state.values)
        if value and self._btn.get("action") != value:
            self._editor.snapshot()
            self._btn["action"] = value
        self._win.grab_release()
        self._win.destroy()
        self._editor.redraw()

    def on_key(self, event):
        s = self._state
        if event.keysym == "Escape":
            s.finish_armed = True
            self._status.configure(text="Finish armed — press Tab to save.")
            return "break"
        if s.finish_armed and event.keysym == "Tab":
            self._finish()
            return "break"
        if event.keysym in _MODIFIER_NAMES:
            name = _MODIFIER_NAMES[event.keysym]
            s.modifier_used.discard(name)
            if name not in s.active:
                s.active.append(name)
            return "break"
        s.finish_armed = False
        s.modifier_used.update(s.active)
        self._add_value(self._display_name(event))
        return "break"

    def on_key_release(self, event):
        if event.keysym not in _MODIFIER_NAMES:
            return "break"
        name = _MODIFIER_NAMES[event.keysym]
        if name in self._state.active:
            self._state.active.remove(name)
        if name not in self._state.modifier_used:
            self._add_value(name)
        return "break"


class Editor(ctk.CTk):
    """Desktop editor for creating and exporting CYD Deck configurations."""

    def __init__(self):
        super().__init__()
        APP_DIR.mkdir(exist_ok=True)
        self.data, self.page, self.selected, self.undo_stack, self.redo_stack = (
            project(),
            0,
            None,
            [],
            [],
        )
        self._save_path: Path | None = None
        self._dirty = False  # true when there are unsaved changes
        self.title("CYD Deck Editor")
        self.geometry("1220x760")
        self.minsize(980, 620)
        ctk.set_appearance_mode("dark")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.make_ui()
        self.enable_drop()
        self.redraw()

    @property
    def profile(self):
        return self.data["profiles"][self.data["activeProfile"]]

    @property
    def current_page(self):
        return self.profile["pages"][self.page]

    def snapshot(self):
        self.undo_stack.append(copy.deepcopy(self.data))
        self.undo_stack = self.undo_stack[-40:]
        self.redo_stack.clear()
        self._dirty = True
        self._update_title()

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(copy.deepcopy(self.data))
            self.data = self.undo_stack.pop()
            self.page = 0
            self.selected = None
            self._dirty = True
            self._update_title()
            self.redraw()

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(copy.deepcopy(self.data))
            self.data = self.redo_stack.pop()
            self.page = 0
            self.selected = None
            self._dirty = True
            self._update_title()
            self.redraw()

    def make_ui(self):
        bar = ctk.CTkFrame(self, corner_radius=0)
        bar.pack(fill="x")
        toolbar_items = [
            ("New", self.new),
            ("Open", self.load),
            ("Save", self.save),
            ("Save As", self.save_as),
            ("Write SD card", self.export_sd),
            ("Undo", self.undo),
            ("Redo", self.redo),
        ]
        for text, command in toolbar_items:
            ctk.CTkButton(bar, text=text, width=105, command=command).pack(
                side="left", padx=4, pady=7
            )
        self.search = ctk.CTkEntry(bar, placeholder_text="Search buttons...")
        self.search.pack(side="right", padx=8, pady=7)
        self.search.bind("<KeyRelease>", lambda e: self.redraw())
        self.bind("<Control-s>", lambda e: self.save())
        self.bind("<Control-S>", lambda e: self.save_as())
        self.bind("<Control-z>", lambda e: self.undo())
        self.bind("<Control-y>", lambda e: self.redo())
        self.side = ctk.CTkFrame(self, width=220)
        self.side.pack(side="left", fill="y", padx=(8, 4), pady=8)
        self.side.pack_propagate(False)
        self.center = ctk.CTkFrame(self)
        self.center.pack(side="left", fill="both", expand=True, padx=4, pady=8)
        self.inspector = ctk.CTkScrollableFrame(self, width=260, label_text="Inspector")
        self.inspector.pack(side="right", fill="y", padx=(4, 8), pady=8)
        self.status = ctk.CTkLabel(self, text="Ready", anchor="w")
        self.status.pack(side="bottom", fill="x", padx=8, pady=(0, 5))

    def redraw(self):
        for f in (self.side, self.center, self.inspector):
            for w in f.winfo_children():
                w.destroy()
        self.draw_sidebar()
        self.draw_grid()
        self.draw_inspector()

    def draw_sidebar(self):
        ctk.CTkLabel(
            self.side, text="PROFILE", font=ctk.CTkFont(size=13, weight="bold")
        ).pack(pady=(14, 5))
        ctk.CTkButton(
            self.side, text=self.profile["name"] + "  ▾", command=self.profile_menu
        ).pack(fill="x", padx=10)
        ctk.CTkLabel(
            self.side, text="PAGES", font=ctk.CTkFont(size=13, weight="bold")
        ).pack(pady=(22, 5))
        page_scroll = ctk.CTkScrollableFrame(self.side, fg_color="transparent")
        page_scroll.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        for i, p in enumerate(self.profile["pages"]):
            row = ctk.CTkFrame(page_scroll, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkButton(
                row,
                text=p["name"],
                fg_color="#3b8ed0" if i == self.page else "transparent",
                anchor="w",
                height=28,
                command=lambda x=i: self.select_page(x),
            ).pack(side="left", fill="x", expand=True, padx=(4, 2))
        ctk.CTkButton(self.side, text="+ Add page", command=self.add_page).pack(
            fill="x", padx=10, pady=(4, 8)
        )
        ctk.CTkButton(self.side, text="Settings", command=self.settings).pack(
            side="bottom", fill="x", padx=10, pady=12
        )

    def draw_grid(self):
        self._draw_grid_header()
        self._draw_grid_buttons()

    def _draw_grid_header(self):
        head = ctk.CTkFrame(self.center, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=10)
        parent_idx = self._find_parent_page(self.page)
        if parent_idx is not None:
            ctk.CTkButton(
                head,
                text="← Back",
                width=70,
                command=lambda: self.select_page(parent_idx),
            ).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(
            head,
            text=self.current_page["name"],
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(side="left")
        ctk.CTkButton(
            head, text="Import app / shortcut", width=145, command=self.import_apps
        ).pack(side="right", padx=(6, 0))
        ctk.CTkButton(
            head, text="+ Folder", width=90, command=self.add_folder_button
        ).pack(side="right", padx=(6, 0))
        at_cap = len(self.current_page["buttons"]) >= 8
        ctk.CTkButton(
            head,
            text="+ Button",
            width=100,
            command=self.add_button,
            state="disabled" if at_cap else "normal",
        ).pack(side="right")
        if at_cap:
            ctk.CTkLabel(
                head,
                text="(page full — 8 max)",
                text_color="#888",
                font=ctk.CTkFont(size=11),
            ).pack(side="right", padx=(0, 6))

    def _draw_grid_buttons(self):
        grid = ctk.CTkFrame(self.center, fg_color="transparent")
        grid.pack(fill="both", expand=True, padx=15, pady=5)
        for i in range(8):
            grid.grid_columnconfigure(i % 4, weight=1)
            grid.grid_rowconfigure(i // 4, weight=1)
        term = self.search.get().lower()
        items = [
            b
            for b in self.current_page["buttons"]
            if not term or term in b["name"].lower()
        ]
        for i, b in enumerate(items[:8]):
            self._draw_button_card(grid, i, b)

    def _draw_button_card(self, grid, i, b):
        is_folder = b["type"] == "Folder"
        border_color = self._button_border_color(b, is_folder)
        f = ctk.CTkFrame(
            grid, corner_radius=14, border_width=2, border_color=border_color
        )
        f.grid(row=i // 4, column=i % 4, sticky="nsew", padx=7, pady=7)
        f.bind("<Button-1>", lambda e, x=b: self.select(x))
        f.bind("<Double-Button-1>", lambda e, x=b: self.open_folder(x))
        icon_text = "📁" if is_folder else b["type"]
        type_color = "#e6a817" if is_folder else "#9aa4b2"
        ctk.CTkLabel(
            f, text=icon_text, text_color=type_color, font=ctk.CTkFont(size=14)
        ).pack(expand=True)
        if is_folder and b.get("folder"):
            ctk.CTkLabel(
                f,
                text=f'→ {b["folder"]}',
                text_color="#7aadcc",
                font=ctk.CTkFont(size=11),
            ).pack()
        lbl = ctk.CTkLabel(
            f, text=b["name"], wraplength=120, font=ctk.CTkFont(size=16, weight="bold")
        )
        lbl.pack(pady=(0, 10))
        lbl.bind("<Button-1>", lambda e, x=b: self.select(x))
        if is_folder:
            ctk.CTkLabel(
                f,
                text="double-click to open",
                text_color="#555",
                font=ctk.CTkFont(size=10),
            ).pack(pady=(0, 6))

    def _button_border_color(self, b, is_folder):
        if is_folder and b is not self.selected:
            return "#e6a817"
        if b is self.selected:
            return "#3b8ed0"
        return "#2b2b2b"

    def draw_inspector(self):
        if not self.selected:
            ctk.CTkLabel(
                self.inspector, text="Select a button to edit it.", wraplength=220
            ).pack(pady=25)
            return
        b = self.selected
        ctk.CTkLabel(
            self.inspector, text="BUTTON", font=ctk.CTkFont(weight="bold")
        ).pack(pady=(14, 4))
        self.field("Name", b, "name")
        self.choice("Type", b, "type", TYPES)
        if b["type"] == "Folder":
            self._draw_folder_inspector(b)
        else:
            self.field("Action / value", b, "action")
            if b["type"] == "Keyboard Shortcut":
                self._draw_shortcut_recorder(b)
        self._draw_toggle_section(b)
        ctk.CTkButton(self.inspector, text="Duplicate", command=self.duplicate).pack(
            fill="x", padx=10, pady=4
        )
        ctk.CTkButton(
            self.inspector,
            text="Delete",
            fg_color="#a33",
            hover_color="#822",
            command=self.delete,
        ).pack(fill="x", padx=10, pady=4)

    def _draw_toggle_section(self, b):
        self.field("Toggle label", b, "toggleName")
        self.field("Toggle action", b, "toggleAction")
        v = tk.BooleanVar(value=b["toggle"])

        def set_toggle():
            if b.get("toggle") != v.get():
                self.snapshot()
                b["toggle"] = v.get()

        ctk.CTkCheckBox(
            self.inspector, text="Smart toggle", variable=v, command=set_toggle
        ).pack(anchor="w", padx=12, pady=8)

    def _draw_folder_inspector(self, b):
        ctk.CTkLabel(self.inspector, text="Target page", anchor="w").pack(
            fill="x", padx=12, pady=(9, 0)
        )
        page_names = [p["name"] for p in self.profile["pages"]]
        current_val = b.get("folder", "") or "(none)"
        options = ["(none)"] + page_names

        def on_pick(choice):
            value = "" if choice == "(none)" else choice
            if b.get("folder") != value:
                self.snapshot()
                b["folder"] = value
                self.redraw()

        ctk.CTkOptionMenu(
            self.inspector,
            values=options,
            variable=tk.StringVar(
                value=current_val if current_val in options else "(none)"
            ),
            command=on_pick,
        ).pack(fill="x", padx=12)
        linked_idx = next(
            (
                i
                for i, p in enumerate(self.profile["pages"])
                if p["name"] == b.get("folder", "")
            ),
            None,
        )
        if linked_idx is not None:
            ctk.CTkButton(
                self.inspector,
                text="Open folder page →",
                command=lambda: self.select_page(linked_idx),
            ).pack(fill="x", padx=10, pady=(6, 2))
        ctk.CTkButton(
            self.inspector,
            text="+ Create & link new page",
            command=lambda: self._create_linked_page(b),
        ).pack(fill="x", padx=10, pady=(4, 2))

    def _draw_shortcut_recorder(self, b):
        ctk.CTkButton(
            self.inspector,
            text="Record shortcut",
            command=lambda: self.record_shortcut(b),
        ).pack(fill="x", padx=10, pady=(7, 2))
        ctk.CTkLabel(
            self.inspector,
            text="Record one or more shortcuts. Press Esc, then Tab to finish.",
            text_color="#888",
            wraplength=220,
        ).pack(padx=12, pady=(0, 3))

    def record_shortcut(self, b):
        win = ctk.CTkToplevel(self)
        win.title("Record shortcut")
        win.geometry("390x180")
        win.resizable(False, False)
        ctk.CTkLabel(
            win,
            text="Press the shortcut you want to use",
            font=ctk.CTkFont(size=17, weight="bold"),
        ).pack(pady=(26, 8))
        status = ctk.CTkLabel(
            win,
            text="Keep pressing shortcuts to add them. Press Esc, then Tab, to save.",
            wraplength=330,
        )
        status.pack(padx=20, pady=4)
        state = _ShortcutRecorderState()
        handlers = _ShortcutHandlers(state, status, b, self, win)
        ctk.CTkButton(
            win, text="Cancel", command=lambda: (win.grab_release(), win.destroy())
        ).pack(side="bottom", pady=18)
        win.bind("<KeyPress>", handlers.on_key)
        win.bind("<KeyRelease>", handlers.on_key_release)
        win.protocol("WM_DELETE_WINDOW", lambda: (win.grab_release(), win.destroy()))
        win.grab_set()
        win.focus_force()

    def field(self, label, obj, key):
        ctk.CTkLabel(self.inspector, text=label, anchor="w").pack(
            fill="x", padx=12, pady=(9, 0)
        )
        e = ctk.CTkEntry(self.inspector)
        e.insert(0, obj.get(key, ""))
        e.pack(fill="x", padx=12)

        def commit(w=e, o=obj, k=key):
            val = w.get()
            if o.get(k) != val:
                self.snapshot()
                o[k] = val
                self.redraw()

        e._cyd_commit = commit
        e.bind("<FocusOut>", lambda x: commit())
        e.bind("<Return>", lambda x: commit())

    def choice(self, label, obj, key, values):
        ctk.CTkLabel(self.inspector, text=label, anchor="w").pack(
            fill="x", padx=12, pady=(9, 0)
        )

        def on_change(x):
            self.snapshot()
            obj[key] = x
            self.redraw()

        ctk.CTkOptionMenu(
            self.inspector,
            values=values,
            variable=tk.StringVar(value=obj[key]),
            command=on_change,
        ).pack(fill="x", padx=12)

    def select(self, b):
        self.selected = b
        self.redraw()

    def select_page(self, i):
        self.page = i
        self.selected = None
        self.redraw()

    def add_page(self):
        self.snapshot()
        self.profile["pages"].append(
            {
                "name": f"Page {len(self.profile['pages'])+1}",
                "wallpaper": "",
                "buttons": [],
            }
        )
        self.page = len(self.profile["pages"]) - 1
        self.redraw()

    def _page_menu(self, idx):
        pages = self.profile["pages"]
        win = tk.Toplevel(self)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="#2b2b2b")
        win.geometry(f"+{self.winfo_pointerx()}+{self.winfo_pointery()}")

        def close():
            win.destroy()

        def action(fn):
            close()
            fn()

        self._page_menu_buttons(win, idx, pages, action)
        win.bind("<FocusOut>", lambda e: close())
        win.focus_force()

    def _page_menu_buttons(self, win, idx, pages, action):
        cfg = dict(
            anchor="w", fg_color="transparent", hover_color="#3a3a3a", corner_radius=4
        )
        ctk.CTkButton(
            win,
            text="✏  Rename",
            width=160,
            **cfg,
            command=lambda: action(lambda: self._rename_page(idx)),
        ).pack(fill="x", padx=4, pady=(4, 1))
        ctk.CTkButton(
            win,
            text="↑  Move up",
            width=160,
            **cfg,
            state="normal" if idx > 0 else "disabled",
            command=lambda: action(lambda: self._move_page(idx, -1)),
        ).pack(fill="x", padx=4, pady=1)
        ctk.CTkButton(
            win,
            text="↓  Move down",
            width=160,
            **cfg,
            state="normal" if idx < len(pages) - 1 else "disabled",
            command=lambda: action(lambda: self._move_page(idx, 1)),
        ).pack(fill="x", padx=4, pady=1)
        ctk.CTkFrame(win, height=1, fg_color="#444").pack(fill="x", padx=6, pady=4)
        ctk.CTkButton(
            win,
            text="🗑  Delete",
            width=160,
            text_color="#e05555",
            anchor="w",
            fg_color="transparent",
            hover_color="#3a3a3a",
            corner_radius=4,
            state="normal" if len(pages) > 1 else "disabled",
            command=lambda: action(lambda: self._delete_page(idx)),
        ).pack(fill="x", padx=4, pady=(1, 4))

    def _rename_page(self, idx):
        pages = self.profile["pages"]
        old = pages[idx]["name"]
        new = simpledialog.askstring(
            "Rename page", "New name:", initialvalue=old, parent=self
        )
        if not new or new == old:
            return
        self.snapshot()
        for p in pages:
            for b in p.get("buttons", []):
                if b.get("type") == "Folder" and b.get("folder") == old:
                    b["folder"] = new
        pages[idx]["name"] = new
        self.redraw()

    def _move_page(self, idx, direction):
        pages = self.profile["pages"]
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(pages):
            return
        self.snapshot()
        pages[idx], pages[new_idx] = pages[new_idx], pages[idx]
        if self.page == idx:
            self.page = new_idx
        elif self.page == new_idx:
            self.page = idx
        self.redraw()

    def _delete_page(self, idx):
        pages = self.profile["pages"]
        if len(pages) <= 1:
            messagebox.showinfo("Cannot delete", "You need at least one page.")
            return
        if not messagebox.askyesno(
            "Delete page", f'Delete "{pages[idx]["name"]}" and all its buttons?'
        ):
            return
        self.snapshot()
        pages.pop(idx)
        self.page = min(self.page, len(pages) - 1)
        self.selected = None
        self.redraw()

    def add_button(self):
        if len(self.current_page["buttons"]) >= 8:
            messagebox.showinfo("Page full", "A page holds a maximum of 8 buttons.")
            return
        self.snapshot()
        b = button(f"Button {len(self.current_page['buttons'])+1}")
        self.current_page["buttons"].append(b)
        self.selected = b
        self.redraw()

    def add_folder_button(self):
        if len(self.current_page["buttons"]) >= 8:
            messagebox.showinfo("Page full", "A page holds a maximum of 8 buttons.")
            return
        name = simpledialog.askstring("New Folder", "Folder name:", parent=self)
        if not name:
            return
        self.snapshot()
        b = button(name)
        b["type"] = "Folder"
        self.profile["pages"].append({"name": name, "wallpaper": "", "buttons": []})
        b["folder"] = name
        self.current_page["buttons"].append(b)
        self.selected = b
        self.redraw()
        self.status.configure(text=f"Folder '{name}' created. Double-click to open.")

    def _create_linked_page(self, b):
        name = simpledialog.askstring(
            "New page", "Page name:", parent=self, initialvalue=b.get("name", "")
        )
        if not name:
            return
        if name in [p["name"] for p in self.profile["pages"]]:
            messagebox.showerror("Name taken", "A page with that name already exists.")
            return
        self.snapshot()
        self.profile["pages"].append({"name": name, "wallpaper": "", "buttons": []})
        b["folder"] = name
        self.redraw()
        self.status.configure(text=f"Page '{name}' created and linked.")

    def _find_parent_page(self, page_idx):
        target = self.profile["pages"][page_idx]["name"]
        for i, p in enumerate(self.profile["pages"]):
            if i == page_idx:
                continue
            for btn in p.get("buttons", []):
                if btn.get("type") == "Folder" and btn.get("folder") == target:
                    return i
        return None

    def enable_drop(self):
        if sys.version_info >= (3, 14):
            self.status.configure(
                text="Use 'Import app / shortcut' (drag/drop requires a Python 3.14 compatible tkinterdnd2)."
            )
            return
        if not TkinterDnD:
            self.status.configure(
                text="Drag/drop optional: install tkinterdnd2, or use Import app / shortcut."
            )
            return
        try:
            TkinterDnD._require(self)
            self.tk.call("tkdnd::drop_target", "register", self._w, DND_FILES)
            self.bind("<<Drop>>", self.on_drop)
            self.status.configure(text="Drop .exe, .lnk, .url, or folders anywhere.")
        except Exception:
            self.status.configure(
                text="Drag/drop unavailable; use Import app / shortcut."
            )

    def on_drop(self, event):
        try:
            self.add_app_paths([Path(p) for p in self.tk.splitlist(event.data)])
        except Exception as e:
            messagebox.showerror("Cannot import dropped item", str(e))

    def import_apps(self):
        paths = filedialog.askopenfilenames(
            title="Choose Windows apps or shortcuts",
            filetypes=[
                ("Apps and shortcuts", "*.exe *.lnk *.url *.bat *.cmd"),
                ("All files", "*.*"),
            ],
        )
        if paths:
            self.add_app_paths([Path(p) for p in paths])

    def shortcut_target(self, path):
        if path.suffix.lower() == ".url":
            for line in path.read_text(errors="ignore").splitlines():
                if line.upper().startswith("URL="):
                    return line[4:].strip()
        if path.suffix.lower() == ".lnk":
            script = "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($args[0]); $s.TargetPath"
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script, str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        return str(path)

    def add_app_paths(self, paths):
        slots = 8 - len(self.current_page["buttons"])
        if slots <= 0:
            messagebox.showinfo("Page full", "A page holds a maximum of 8 buttons.")
            return
        self.snapshot()
        added = []
        for path in paths[:slots]:
            target = self.shortcut_target(path)
            name = path.stem
            if path.suffix.lower() == ".lnk" and target:
                name = Path(target).stem or name
            # .url files are websites, not applications
            btn_type = "Website" if path.suffix.lower() == ".url" else "Application"
            b = button(name)
            b.update(type=btn_type, action=target)
            self.current_page["buttons"].append(b)
            added.append(name)
        if added:
            self.selected = self.current_page["buttons"][-1]
            self.redraw()
            suffix = " (page limit reached)" if len(paths) > slots else ""
            self.status.configure(text="Added: " + ", ".join(added) + suffix)

    def delete(self):
        self.snapshot()
        self.current_page["buttons"].remove(self.selected)
        self.selected = None
        self.redraw()

    def duplicate(self):
        if len(self.current_page["buttons"]) >= 8:
            messagebox.showinfo("Page full", "A page holds a maximum of 8 buttons.")
            return
        self.snapshot()
        b = copy.deepcopy(self.selected)
        b["id"] = str(uuid.uuid4())
        b["name"] += " Copy"
        self.current_page["buttons"].append(b)
        self.selected = b
        self.redraw()

    def open_folder(self, b):
        if b["type"] != "Folder":
            return
        target = b.get("folder", "")
        if target:
            for i, p in enumerate(self.profile["pages"]):
                if p["name"] == target:
                    self.select_page(i)
                    return
        if messagebox.askyesno(
            "No linked page", f'"{b["name"]}" has no folder page yet.\nCreate one now?'
        ):
            self._create_linked_page(b)

    def profile_menu(self):
        name = simpledialog.askstring(
            "Profile", "New profile name (blank to cancel):", parent=self
        )
        if name:
            self.snapshot()
            self.data["profiles"].append(
                {
                    "id": str(uuid.uuid4()),
                    "name": name,
                    "pages": [{"name": "Home", "wallpaper": "", "buttons": []}],
                }
            )
            self.data["activeProfile"] = len(self.data["profiles"]) - 1
            self.page = 0
            self.redraw()

    def settings(self):
        win = ctk.CTkToplevel(self)
        win.title("Deck Settings")
        win.geometry("350x320")
        ctk.CTkLabel(win, text="Device name").pack(pady=(25, 0))
        name = ctk.CTkEntry(win)
        name.insert(0, self.data["deviceName"])
        name.pack(padx=25, fill="x")
        ctk.CTkLabel(win, text="Brightness").pack(pady=(15, 0))
        bright = ctk.CTkSlider(win, from_=10, to=255)
        bright.set(self.data["brightness"])
        bright.pack(padx=25, fill="x")
        theme = ctk.CTkOptionMenu(
            win, values=["Dark", "OLED Black", "Blue", "Purple", "Green"]
        )
        theme.set(self.data.get("theme", "Dark"))
        theme.pack(padx=25, pady=15)

        def save_settings():
            updated = {
                "deviceName": name.get(),
                "brightness": int(bright.get()),
                "theme": theme.get(),
            }
            if any(self.data.get(key) != value for key, value in updated.items()):
                self.snapshot()
                self.data.update(updated)
            win.destroy()
            self.redraw()

        ctk.CTkButton(win, text="Save settings", command=save_settings).pack(pady=12)

    def new(self):
        self.data = project()
        self.page = 0
        self.selected = None
        self.undo_stack = []
        self.redo_stack = []
        self._save_path = None
        self._dirty = False
        self._update_title()
        self.redraw()

    def _update_title(self):
        name = self._save_path.name if self._save_path else "Untitled"
        dirty = " •" if self._dirty else ""
        self.title(f"CYD Deck Editor — {name}{dirty}")

    def _on_close(self):
        if self._dirty:
            if not messagebox.askyesno(
                "Unsaved changes", "You have unsaved changes. Close anyway?"
            ):
                return
        self.quit()

    def save(self):
        if self._save_path is None:
            self.save_as()
            return
        # Commit any text field that still has focus before writing to disk.
        focused_widget = self.focus_get()
        commit = getattr(focused_widget, "_cyd_commit", None)
        if commit:
            commit()
        try:
            self._save_path.write_text(json.dumps(self.data, indent=2), encoding="utf8")
            self._dirty = False
            self._update_title()
            self.status.configure(text=f"Saved: {self._save_path}")
        except OSError as e:
            messagebox.showerror("Cannot save", str(e))

    def save_as(self):
        path = filedialog.asksaveasfilename(
            title="Save deck file",
            defaultextension=".deck",
            filetypes=[("CYD Deck", "*.deck"), ("JSON", "*.json")],
            initialfile=self._save_path.name if self._save_path else "my_deck.deck",
        )
        if not path:
            return
        self._save_path = Path(path)
        self.save()

    def export_sd(self):
        folder = self._pick_sd_folder()
        if not folder:
            return
        path = Path(folder) / "deck.deck"
        try:
            path.write_text(json.dumps(self.data, indent=2), encoding="utf8")
            self.status.configure(text=f"Copied to SD card: {path}")
        except OSError as e:
            messagebox.showerror("Cannot write SD card", str(e))

    def _pick_sd_folder(self) -> str:
        drives: list[str] = []
        if sys.platform == "win32":
            mask = ctypes.windll.kernel32.GetLogicalDrives()
            for i in range(26):
                root = f"{chr(65 + i)}:\\"
                if mask & (1 << i) and ctypes.windll.kernel32.GetDriveTypeW(root) == 2:
                    drives.append(root)
        if len(drives) == 1:
            if not messagebox.askyesno(
                "Write SD card", f"Write deck.deck to {drives[0]}?"
            ):
                return ""
            return drives[0]
        return filedialog.askdirectory(title="Choose the root of your SD card")

    def load(self):
        path = filedialog.askopenfilename(
            filetypes=[("CYD Deck", "*.deck"), ("JSON", "*.json")]
        )
        if not path:
            return
        try:
            try:
                self.data = json.loads(Path(path).read_text(encoding="utf8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                with zipfile.ZipFile(path) as z:
                    self.data = json.loads(z.read("config.json"))
            self._save_path = Path(path)
            self.page = 0
            self.selected = None
            self._dirty = False
            self._update_title()
            self.redraw()
            self.status.configure(text=f"Loaded {path}")
        except Exception as e:
            messagebox.showerror("Cannot load", str(e))

    # send_ble / ble_task are intentionally omitted: the firmware does not expose
    # a config GATT characteristic — SD card is the only supported transport.


if __name__ == "__main__":
    Editor().mainloop()
