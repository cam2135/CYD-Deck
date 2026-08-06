"""CYD Deck Editor - single-file Windows configuration application.

Install once:  py -m pip install customtkinter bleak pillow tkinterdnd2
The editor remains useful without BLE: projects can be saved as .deck files and
later sent to a CYD using the Connect & Send button.
"""
from __future__ import annotations
import asyncio, copy, ctypes, json, shutil, subprocess, sys, threading, uuid, zipfile
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import customtkinter as ctk
from PIL import Image, ImageTk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:
    DND_FILES = TkinterDnD = None

try:
    from bleak import BleakScanner, BleakClient
except ImportError:
    BleakScanner = BleakClient = None

APP_DIR = Path.home() / "CYDDeck"; ASSET_DIR = APP_DIR / "assets"
CONFIG_UUID = "9f3c1001-8f9d-4e9c-a9d4-a56e6b440001"
STATUS_UUID = "9f3c1002-8f9d-4e9c-a9d4-a56e6b440001"
TYPES = ["Keyboard Shortcut", "Macro", "Folder", "Application", "Website", "Media", "Volume", "Brightness", "OBS", "Discord", "Clipboard", "Open File", "Open Folder", "Lock PC", "Sleep", "Restart", "Shutdown", "Timer", "Stopwatch", "Soundboard", "Custom"]

def button(name="New Button"):
    return {"id": str(uuid.uuid4()), "name": name, "type": "Keyboard Shortcut", "action": "", "icon": "", "toggle": False, "toggleName": "", "toggleAction": "", "folder": ""}

def project():
    return {"version": 1, "deviceName": "CYD Deck", "theme": "Dark", "brightness": 180, "wallpaper": "", "profiles": [{"id": "default", "name": "Default", "pages": [{"name": "Home", "wallpaper": "", "buttons": []}]}], "activeProfile": 0}

class Editor(ctk.CTk):
    def __init__(self):
        super().__init__(); APP_DIR.mkdir(exist_ok=True); ASSET_DIR.mkdir(exist_ok=True)
        self.data, self.page, self.selected, self.undo_stack, self.redo_stack = project(), 0, None, [], []
        self._save_path: Path | None = None  # tracks the current file location for quick-save
        self.title("CYD Deck Editor"); self.geometry("1220x760"); self.minsize(980, 620)
        ctk.set_appearance_mode("dark"); self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.make_ui(); self.enable_drop(); self.redraw()

    @property
    def profile(self): return self.data["profiles"][self.data["activeProfile"]]
    @property
    def current_page(self): return self.profile["pages"][self.page]
    def snapshot(self):
        self.undo_stack.append(copy.deepcopy(self.data)); self.undo_stack = self.undo_stack[-40:]; self.redo_stack.clear()
    def undo(self):
        if self.undo_stack: self.redo_stack.append(copy.deepcopy(self.data)); self.data = self.undo_stack.pop(); self.page=0; self.selected=None; self.redraw()
    def redo(self):
        if self.redo_stack: self.undo_stack.append(copy.deepcopy(self.data)); self.data = self.redo_stack.pop(); self.page=0; self.selected=None; self.redraw()
    def make_ui(self):
        bar=ctk.CTkFrame(self, corner_radius=0); bar.pack(fill="x")
        for text, command in [("New",self.new), ("Open",self.load), ("Save",self.save), ("Save As",self.save_as), ("Write SD card",self.export_sd), ("Undo",self.undo), ("Redo",self.redo)]: ctk.CTkButton(bar,text=text,width=105,command=command).pack(side="left",padx=4,pady=7)
        self.search=ctk.CTkEntry(bar,placeholder_text="Search buttons..."); self.search.pack(side="right",padx=8,pady=7); self.search.bind("<KeyRelease>",lambda e:self.redraw())
        # Keyboard shortcuts
        self.bind("<Control-s>", lambda e: self.save())
        self.bind("<Control-S>", lambda e: self.save_as())
        self.bind("<Control-z>", lambda e: self.undo())
        self.bind("<Control-y>", lambda e: self.redo())
        self.side=ctk.CTkFrame(self,width=220); self.side.pack(side="left",fill="y",padx=(8,4),pady=8); self.side.pack_propagate(False)
        self.center=ctk.CTkFrame(self); self.center.pack(side="left",fill="both",expand=True,padx=4,pady=8)
        self.inspector=ctk.CTkScrollableFrame(self,width=260,label_text="Inspector"); self.inspector.pack(side="right",fill="y",padx=(4,8),pady=8)
        self.status=ctk.CTkLabel(self,text="Ready",anchor="w"); self.status.pack(side="bottom",fill="x",padx=8,pady=(0,5))
    def redraw(self):
        for f in (self.side,self.center,self.inspector):
            for w in f.winfo_children(): w.destroy()
        self.draw_sidebar(); self.draw_grid(); self.draw_inspector()
    def draw_sidebar(self):
        ctk.CTkLabel(self.side,text="PROFILE",font=ctk.CTkFont(size=13,weight="bold")).pack(pady=(14,5))
        ctk.CTkButton(self.side,text=self.profile["name"]+"  ▾",command=self.profile_menu).pack(fill="x",padx=10)
        ctk.CTkLabel(self.side,text="PAGES",font=ctk.CTkFont(size=13,weight="bold")).pack(pady=(22,5))

        # Scrollable page list — expands to fill available space, stops before the bottom buttons
        page_scroll = ctk.CTkScrollableFrame(self.side, fg_color="transparent")
        page_scroll.pack(fill="both", expand=True, padx=4, pady=(0,4))

        for i, p in enumerate(self.profile["pages"]):
            row = ctk.CTkFrame(page_scroll, fg_color="transparent")
            row.pack(fill="x", pady=2)

            is_active = (i == self.page)
            ctk.CTkButton(
                row, text=p["name"],
                fg_color="#3b8ed0" if is_active else "transparent",
                anchor="w", height=28,
                command=lambda x=i: self.select_page(x)
            ).pack(fill="x", expand=True, padx=4)

        ctk.CTkButton(self.side,text="+ Add page",command=self.add_page).pack(fill="x",padx=10,pady=(4,8))
        ctk.CTkButton(self.side,text="Settings",command=self.settings).pack(side="bottom",fill="x",padx=10,pady=12)
    def draw_grid(self):
        head=ctk.CTkFrame(self.center,fg_color="transparent"); head.pack(fill="x",padx=12,pady=10)
        # Breadcrumb: if this page is a folder target, show a back arrow button.
        parent_idx = self._find_parent_page(self.page)
        if parent_idx is not None:
            ctk.CTkButton(head,text="← Back",width=70,command=lambda:self.select_page(parent_idx)).pack(side="left",padx=(0,8))
        ctk.CTkLabel(head,text=self.current_page["name"],font=ctk.CTkFont(size=22,weight="bold")).pack(side="left")
        ctk.CTkButton(head,text="Import app / shortcut",width=145,command=self.import_apps).pack(side="right",padx=(6,0))
        ctk.CTkButton(head,text="+ Folder",width=90,command=self.add_folder_button).pack(side="right",padx=(6,0))
        ctk.CTkButton(head,text="+ Button",width=100,command=self.add_button).pack(side="right")
        grid=ctk.CTkFrame(self.center,fg_color="transparent"); grid.pack(fill="both",expand=True,padx=15,pady=5)
        for i in range(8): grid.grid_columnconfigure(i%4,weight=1); grid.grid_rowconfigure(i//4,weight=1)
        term=self.search.get().lower(); items=[b for b in self.current_page["buttons"] if not term or term in b["name"].lower()]
        for i,b in enumerate(items[:8]):
            is_folder = b["type"] == "Folder"
            border_col = "#e6a817" if is_folder else None
            f=ctk.CTkFrame(grid,corner_radius=14,border_width=2,border_color=border_col if is_folder and b is not self.selected else ("#3b8ed0" if b is self.selected else "#2b2b2b"))
            f.grid(row=i//4,column=i%4,sticky="nsew",padx=7,pady=7); f.bind("<Button-1>",lambda e,x=b:self.select(x))
            # Folder icon or type label
            icon_text = "📁" if is_folder else b["type"]
            type_color = "#e6a817" if is_folder else "#9aa4b2"
            ctk.CTkLabel(f,text=icon_text,text_color=type_color,font=ctk.CTkFont(size=14)).pack(expand=True)
            # Show linked page name under folder buttons
            if is_folder and b.get("folder"):
                ctk.CTkLabel(f,text=f'→ {b["folder"]}',text_color="#7aadcc",font=ctk.CTkFont(size=11)).pack()
            l=ctk.CTkLabel(f,text=b["name"],wraplength=120,font=ctk.CTkFont(size=16,weight="bold")); l.pack(pady=(0,10)); l.bind("<Button-1>",lambda e,x=b:self.select(x))
            if is_folder:
                ctk.CTkLabel(f,text="double-click to open",text_color="#555",font=ctk.CTkFont(size=10)).pack(pady=(0,6))
            f.bind("<Double-Button-1>",lambda e,x=b:self.open_folder(x))
    def draw_inspector(self):
        if not self.selected:
            ctk.CTkLabel(self.inspector,text="Select a button to edit it.",wraplength=220).pack(pady=25); return
        b=self.selected; ctk.CTkLabel(self.inspector,text="BUTTON",font=ctk.CTkFont(weight="bold")).pack(pady=(14,4))
        self.field("Name",b,"name"); self.choice("Type",b,"type",TYPES)
        if b["type"]=="Folder":
            self._draw_folder_inspector(b)
        else:
            self.field("Action / value",b,"action")
        self.field("Toggle label",b,"toggleName"); self.field("Toggle action",b,"toggleAction")
        v=tk.BooleanVar(value=b["toggle"]); ctk.CTkCheckBox(self.inspector,text="Smart toggle",variable=v,command=lambda: b.update(toggle=v.get())).pack(anchor="w",padx=12,pady=8)
        ctk.CTkButton(self.inspector,text="Duplicate",command=self.duplicate).pack(fill="x",padx=10,pady=4)
        ctk.CTkButton(self.inspector,text="Delete",fg_color="#a33",hover_color="#822",command=self.delete).pack(fill="x",padx=10,pady=4)

    def _draw_folder_inspector(self, b):
        """Folder-specific inspector section: page picker + create-new shortcut."""
        ctk.CTkLabel(self.inspector,text="Target page",anchor="w").pack(fill="x",padx=12,pady=(9,0))
        page_names=[p["name"] for p in self.profile["pages"]]
        current_val=b.get("folder","") or "(none)"
        options=["(none)"]+page_names
        def on_pick(choice):
            b["folder"]="" if choice=="(none)" else choice
            self.redraw()
        ctk.CTkOptionMenu(self.inspector,values=options,variable=tk.StringVar(value=current_val if current_val in options else "(none)"),command=on_pick).pack(fill="x",padx=12)
        # If the linked page exists, offer a button to jump to it.
        linked_idx=next((i for i,p in enumerate(self.profile["pages"]) if p["name"]==b.get("folder","")),None)
        if linked_idx is not None:
            ctk.CTkButton(self.inspector,text="Open folder page →",command=lambda:self.select_page(linked_idx)).pack(fill="x",padx=10,pady=(6,2))
        # Always offer to create a brand-new page and link it.
        ctk.CTkButton(self.inspector,text="+ Create & link new page",command=lambda:self._create_linked_page(b)).pack(fill="x",padx=10,pady=(4,2))
    def field(self,label,obj,key):
        ctk.CTkLabel(self.inspector,text=label,anchor="w").pack(fill="x",padx=12,pady=(9,0)); e=ctk.CTkEntry(self.inspector); e.insert(0,obj.get(key,"")); e.pack(fill="x",padx=12); e.bind("<FocusOut>",lambda x,o=obj,k=key,w=e:o.update({k:w.get()}) or self.redraw())
    def choice(self,label,obj,key,values):
        ctk.CTkLabel(self.inspector,text=label,anchor="w").pack(fill="x",padx=12,pady=(9,0)); ctk.CTkOptionMenu(self.inspector,values=values,variable=tk.StringVar(value=obj[key]),command=lambda x:obj.update({key:x}) or self.redraw()).pack(fill="x",padx=12)
    def select(self,b): self.selected=b; self.redraw()
    def select_page(self,i): self.page=i; self.selected=None; self.redraw()
    def add_page(self): self.snapshot(); self.profile["pages"].append({"name":f"Page {len(self.profile['pages'])+1}","wallpaper":"","buttons":[]}); self.page=len(self.profile["pages"])-1; self.redraw()

    def _page_menu(self, idx):
        """Show a small popup menu with actions for the page at idx."""
        pages = self.profile["pages"]
        win = tk.Toplevel(self)
        win.overrideredirect(True)   # borderless popup
        win.attributes("-topmost", True)
        win.configure(bg="#2b2b2b")

        # Position near the ⋯ button using current mouse coords
        win.geometry(f"+{self.winfo_pointerx()}+{self.winfo_pointery()}")

        def close(): win.destroy()
        def action(fn): close(); fn()

        btn_cfg = dict(anchor="w", fg_color="transparent", hover_color="#3a3a3a", corner_radius=4)

        ctk.CTkButton(win, text="✏  Rename",  width=160, **btn_cfg, command=lambda: action(lambda: self._rename_page(idx))).pack(fill="x", padx=4, pady=(4,1))
        ctk.CTkButton(win, text="↑  Move up",  width=160, **btn_cfg,
                      state="normal" if idx > 0 else "disabled",
                      command=lambda: action(lambda: self._move_page(idx, -1))).pack(fill="x", padx=4, pady=1)
        ctk.CTkButton(win, text="↓  Move down", width=160, **btn_cfg,
                      state="normal" if idx < len(pages)-1 else "disabled",
                      command=lambda: action(lambda: self._move_page(idx, +1))).pack(fill="x", padx=4, pady=1)

        # Separator
        ctk.CTkFrame(win, height=1, fg_color="#444").pack(fill="x", padx=6, pady=4)

        ctk.CTkButton(win, text="🗑  Delete", width=160, text_color="#e05555",
                      anchor="w", fg_color="transparent", hover_color="#3a3a3a", corner_radius=4,
                      state="normal" if len(pages) > 1 else "disabled",
                      command=lambda: action(lambda: self._delete_page(idx))).pack(fill="x", padx=4, pady=(1,4))

        # Dismiss on click anywhere outside
        win.bind("<FocusOut>", lambda e: close())
        win.focus_force()

    def _rename_page(self, idx):
        pages = self.profile["pages"]
        old_name = pages[idx]["name"]
        new_name = simpledialog.askstring("Rename page", "New name:", initialvalue=old_name, parent=self)
        if not new_name or new_name == old_name: return
        self.snapshot()
        # Update any Folder buttons pointing at this page
        for p in pages:
            for b in p.get("buttons", []):
                if b.get("type") == "Folder" and b.get("folder") == old_name:
                    b["folder"] = new_name
        pages[idx]["name"] = new_name
        self.redraw()

    def _move_page(self, idx, direction):
        """Swap page at idx with the one above (-1) or below (+1) it."""
        pages = self.profile["pages"]
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(pages): return
        self.snapshot()
        pages[idx], pages[new_idx] = pages[new_idx], pages[idx]
        # Keep the selected page in focus
        if self.page == idx:
            self.page = new_idx
        elif self.page == new_idx:
            self.page = idx
        self.redraw()

    def _delete_page(self, idx):
        pages = self.profile["pages"]
        if len(pages) <= 1:
            messagebox.showinfo("Cannot delete", "You need at least one page."); return
        name = pages[idx]["name"]
        if not messagebox.askyesno("Delete page", f'Delete "{name}" and all its buttons?'): return
        self.snapshot()
        pages.pop(idx)
        # Clamp current page index
        self.page = min(self.page, len(pages) - 1)
        self.selected = None
        self.redraw()
    def add_button(self): self.snapshot(); b=button(f"Button {len(self.current_page['buttons'])+1}"); self.current_page["buttons"].append(b); self.selected=b; self.redraw()
    def add_folder_button(self):
        """Add a Folder button and immediately create+link a new page for it."""
        self.snapshot()
        name=simpledialog.askstring("New Folder","Folder name:", parent=self)
        if not name: return
        b=button(name); b["type"]="Folder"
        # Create the destination page and link it.
        new_page={"name":name,"wallpaper":"","buttons":[]}
        self.profile["pages"].append(new_page); b["folder"]=name
        self.current_page["buttons"].append(b); self.selected=b; self.redraw()
        self.status.configure(text=f"Folder '{name}' created. Double-click it to open, or use the inspector to edit its page.")
    def _create_linked_page(self, b):
        """Create a new page and link it to an existing folder button."""
        self.snapshot()
        name=simpledialog.askstring("New page","Page name (will be linked to this folder button):", parent=self, initialvalue=b.get("name",""))
        if not name: return
        # Avoid duplicate page names.
        existing=[p["name"] for p in self.profile["pages"]]
        if name in existing:
            messagebox.showerror("Name taken","A page with that name already exists. Pick the existing one from the dropdown instead."); return
        self.profile["pages"].append({"name":name,"wallpaper":"","buttons":[]})
        b["folder"]=name; self.redraw()
        self.status.configure(text=f"Page '{name}' created and linked.")
    def _find_parent_page(self, page_idx):
        """Return the index of the page that has a Folder button pointing at this page, or None."""
        target=self.profile["pages"][page_idx]["name"]
        for i,p in enumerate(self.profile["pages"]):
            if i==page_idx: continue
            for btn in p.get("buttons",[]):
                if btn.get("type")=="Folder" and btn.get("folder")==target: return i
        return None
    def enable_drop(self):
        """Enable Windows Explorer file drops without requiring elevated rights."""
        # tkinterdnd2 currently sends legacy event fields that Python 3.14's
        # tkinter rejects ("expected integer but got %#"). The file picker
        # remains available and is reliable on every supported Python version.
        if sys.version_info >= (3, 14):
            self.status.configure(text="Use ‘Import app / shortcut’ (drag/drop awaits a Python 3.14 compatible tkinterdnd2 release)."); return
        if not TkinterDnD:
            self.status.configure(text="Drag/drop optional: install tkinterdnd2, or use Import app / shortcut."); return
        try:
            TkinterDnD._require(self); self.tk.call("tkdnd::drop_target", "register", self._w, DND_FILES)
            self.bind("<<Drop>>", self.on_drop); self.status.configure(text="Drop .exe, .lnk, .url, or folders anywhere in this window.")
        except Exception as e: self.status.configure(text="Drag/drop unavailable; use Import app / shortcut.")
    def on_drop(self,event):
        try: self.add_app_paths([Path(p) for p in self.tk.splitlist(event.data)])
        except Exception as e: messagebox.showerror("Cannot import dropped item",str(e))
    def import_apps(self):
        paths=filedialog.askopenfilenames(title="Choose Windows apps or shortcuts",filetypes=[("Apps and shortcuts","*.exe *.lnk *.url *.bat *.cmd"),("All files","*.*")])
        if paths:self.add_app_paths([Path(p) for p in paths])
    def shortcut_target(self,path):
        """Resolve an Explorer shortcut using Windows' built-in WScript COM object."""
        if path.suffix.lower()==".url":
            for line in path.read_text(errors="ignore").splitlines():
                if line.upper().startswith("URL="): return line[4:].strip()
        if path.suffix.lower()==".lnk":
            script="$s=(New-Object -ComObject WScript.Shell).CreateShortcut($args[0]); $s.TargetPath"
            result=subprocess.run(["powershell","-NoProfile","-Command",script,str(path)],capture_output=True,text=True,check=False)
            if result.returncode==0 and result.stdout.strip(): return result.stdout.strip()
        return str(path)
    def add_app_paths(self,paths):
        self.snapshot(); added=[]
        for path in paths:
            target=self.shortcut_target(path); name=path.stem
            if path.suffix.lower()==".lnk" and target: name=Path(target).stem or name
            b=button(name); b.update(type="Application",action=target,icon=""); self.current_page["buttons"].append(b); added.append(name)
        if added: self.selected=self.current_page["buttons"][-1]; self.redraw(); self.status.configure(text="Added: "+", ".join(added))
    def delete(self): self.snapshot(); self.current_page["buttons"].remove(self.selected); self.selected=None; self.redraw()
    def duplicate(self): self.snapshot(); b=copy.deepcopy(self.selected); b["id"]=str(uuid.uuid4()); b["name"] += " Copy"; self.current_page["buttons"].append(b); self.selected=b; self.redraw()
    def open_folder(self,b):
        if b["type"]!="Folder": return
        target=b.get("folder","")
        if target:
            for i,p in enumerate(self.profile["pages"]):
                if p["name"]==target: self.select_page(i); return
        # No linked page yet — offer to create one.
        if messagebox.askyesno("No linked page",f'"{b["name"]}" has no folder page yet.\nCreate one now?'):
            self._create_linked_page(b)
    def profile_menu(self):
        name=simpledialog.askstring("Profile", "New profile name (blank to cancel):", parent=self)
        if name: self.snapshot(); self.data["profiles"].append({"id":str(uuid.uuid4()),"name":name,"pages":[{"name":"Home","wallpaper":"","buttons":[]}]}); self.data["activeProfile"]=len(self.data["profiles"])-1; self.page=0; self.redraw()
    def settings(self):
        win=ctk.CTkToplevel(self); win.title("Deck Settings"); win.geometry("350x320")
        ctk.CTkLabel(win,text="Device name").pack(pady=(25,0)); name=ctk.CTkEntry(win); name.insert(0,self.data["deviceName"]); name.pack(padx=25,fill="x")
        ctk.CTkLabel(win,text="Brightness").pack(pady=(15,0)); bright=ctk.CTkSlider(win,from_=10,to=255); bright.set(self.data["brightness"]); bright.pack(padx=25,fill="x")
        theme=ctk.CTkOptionMenu(win,values=["Dark","Light","OLED Black","Blue","Purple","Green","Custom"]); theme.set(self.data["theme"]); theme.pack(padx=25,pady=15)
        ctk.CTkButton(win,text="Save settings",command=lambda:self.data.update(deviceName=name.get(),brightness=int(bright.get()),theme=theme.get()) or win.destroy()).pack(pady=12)
    def new(self): self.data=project(); self.page=0; self.selected=None; self.undo_stack=[]; self._save_path=None; self._update_title(); self.redraw()
    def _update_title(self):
        name = self._save_path.name if self._save_path else "Untitled"
        self.title(f"CYD Deck Editor — {name}")
    def _on_close(self):
        if self.undo_stack:
            if not messagebox.askyesno("Unsaved changes", "You have unsaved changes. Close anyway?"): return
        self.quit()
    def save(self):
        """Quick-save to the current file. Falls back to Save As if no file is open."""
        if self._save_path is None:
            self.save_as(); return
        try:
            self._save_path.write_text(json.dumps(self.data, indent=2), encoding="utf8")
            self.undo_stack.clear()  # mark as clean after save
            self._update_title()
            self.status.configure(text=f"Saved: {self._save_path}")
        except OSError as e: messagebox.showerror("Cannot save", str(e))
    def save_as(self):
        """Save to a new location chosen by the user."""
        path=filedialog.asksaveasfilename(
            title="Save deck file",
            defaultextension=".deck",
            filetypes=[("CYD Deck", "*.deck"), ("JSON", "*.json")],
            initialfile=self._save_path.name if self._save_path else "my_deck.deck"
        )
        if not path: return
        self._save_path = Path(path)
        self.save()
    def export_sd(self):
        # Prefer a removable drive automatically, so Export never defaults to
        # saving a deck file in an arbitrary folder on the computer.
        drives=[]
        if sys.platform == "win32":
            mask=ctypes.windll.kernel32.GetLogicalDrives()
            for i in range(26):
                root=f"{chr(65+i)}:\\"
                if mask & (1 << i) and ctypes.windll.kernel32.GetDriveTypeW(root)==2: drives.append(root)
        folder=drives[0] if len(drives)==1 else filedialog.askdirectory(title="Choose the root of your SD card")
        if not folder:return
        path=Path(folder)/"deck.deck"
        try:
            path.write_text(json.dumps(self.data,indent=2),encoding="utf8")
            self.status.configure(text=f"Copied to SD card: {path}")
        except OSError as e: messagebox.showerror("Cannot write SD card",str(e))
    def load(self):
        path=filedialog.askopenfilename(filetypes=[("CYD Deck","*.deck"),("JSON","*.json")]);
        if not path:return
        try:
            try: self.data=json.loads(Path(path).read_text(encoding="utf8"))
            except (UnicodeDecodeError,json.JSONDecodeError):
                # Compatibility with the older ZIP-based .deck export.
                with zipfile.ZipFile(path) as z:self.data=json.loads(z.read("config.json"))
            self._save_path=Path(path); self.page=0; self.selected=None; self._update_title(); self.redraw(); self.status.configure(text=f"Loaded {path}")
        except Exception as e: messagebox.showerror("Cannot load",str(e))
    def send_ble(self):
        if not BleakScanner: messagebox.showerror("BLE unavailable","Install bleak: py -m pip install bleak"); return
        self.status.configure(text="Scanning for CYD Deck..."); threading.Thread(target=lambda:asyncio.run(self.ble_task()),daemon=True).start()
    async def ble_task(self):
        try:
            devs=await BleakScanner.discover(timeout=6); d=next((x for x in devs if x.name and "CYD Deck" in x.name),None)
            if not d: raise RuntimeError("No CYD Deck found. Put the deck in configuration mode.")
            raw=json.dumps(self.data,separators=(",",":"),ensure_ascii=False).encode(); self.after(0,lambda:self.status.configure(text="Sending configuration..."))
            async with BleakClient(d) as client:
                for i in range(0,len(raw),180): await client.write_gatt_char(CONFIG_UUID,raw[i:i+180],response=True)
                await client.write_gatt_char(CONFIG_UUID,b"\nEND\n",response=True)
            self.after(0,lambda:self.status.configure(text="Configuration sent successfully."))
        except Exception as e:
            # Python clears `e` after this block, while Tk executes callbacks later.
            message = str(e)
            self.after(0, lambda: messagebox.showerror("BLE transfer failed", message))

if __name__ == "__main__": Editor().mainloop()
