"""釘選剪貼簿：永遠顯示在最上層的小視窗，只保存「你自己貼進來」的文字，一鍵複製。

不會監看系統剪貼簿：內容只有在你按「儲存」（Ctrl+Enter）或「貼上並儲存」時才會加入。
資料放在使用者資料夾（Windows 是 %APPDATA%\\pinclip），不放在程式資料夾，避免被 git 收進去。
"""
import json
import os
import re
import shutil
import sys
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont

APP_TITLE = "釘選剪貼簿"
DEFAULT_GEOMETRY = "360x480"
MIN_SIZE = (240, 240)
CARD_CHROME = 48      # 卡片左右的外距、內距和邊框（不含按鈕）

BG = "#f4f4f1"
CARD_BG = "#ffffff"
BORDER = "#d4d4cc"
MUTED = "#777777"
ACCENT = "#1f6feb"


def default_data_path():
    override = os.environ.get("PINCLIP_DATA")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "pinclip" / "pinclip.json"


def preview(text, max_lines=3, max_chars=140):
    """卡片上顯示的摘要：最多 max_lines 行、max_chars 字，被截掉時加「…」。"""
    lines = text.strip().splitlines() or [""]
    shown = "\n".join(line.rstrip() for line in lines[:max_lines])
    truncated = len(lines) > max_lines
    if len(shown) > max_chars:
        shown = shown[:max_chars]
        truncated = True
    return shown + ("…" if truncated else "")


_GEOMETRY = re.compile(r"^(\d+)x(\d+)(?:\+(-?\d+)\+(-?\d+))?$")


def fit_geometry(geometry, vx, vy, vw, vh, default=DEFAULT_GEOMETRY):
    """檢查上次存的視窗位置：螢幕拔掉或換解析度後，視窗不能跑到看不見的地方。

    (vx, vy, vw, vh) 是整個虛擬桌面的範圍。尺寸不合理就用 default；
    位置看不到（大部分在畫面外）就只保留尺寸，讓系統自己擺。
    """
    match = _GEOMETRY.match(geometry or "")
    if not match:
        return default
    w, h = int(match.group(1)), int(match.group(2))
    w = max(MIN_SIZE[0], min(w, vw))
    h = max(MIN_SIZE[1], min(h, vh))
    if match.group(3) is None:
        return f"{w}x{h}"
    x, y = int(match.group(3)), int(match.group(4))
    visible = (x + w >= vx + 60 and x <= vx + vw - 60
               and y >= vy and y <= vy + vh - 60)
    return f"{w}x{h}+{x}+{y}" if visible else f"{w}x{h}"


class ClipStore:
    """存放貼進來的文字（最新的在最前面）和視窗設定，存成一個 JSON 檔。"""

    def __init__(self, path):
        self.path = Path(path)
        self.items = []
        self.window = {}
        self.save_failed = False
        self.load()

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            self._keep_bad_copy()
            return
        if not isinstance(data, dict):
            self._keep_bad_copy()
            return
        items = data.get("items")
        if isinstance(items, list):
            self.items = [t for t in items if isinstance(t, str) and t.strip()]
        window = data.get("window")
        if isinstance(window, dict):
            self.window = window

    def _keep_bad_copy(self):
        # 檔案壞掉時留一份，免得下一次儲存把它蓋掉
        try:
            shutil.copy2(self.path, self.path.with_name(self.path.name + ".bad"))
        except OSError:
            pass

    def save(self):
        data = {"version": 1, "items": self.items, "window": self.window}
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            self.save_failed = True
            return False
        self.save_failed = False
        return True

    def add(self, text):
        """加入一筆；空白內容不收。同樣的內容再貼一次，是把舊的移到最前面，不會重複。"""
        if not text.strip():
            return False
        if text in self.items:
            self.items.remove(text)
        self.items.insert(0, text)
        self.save()
        return True

    def remove(self, index):
        text = self.items.pop(index)
        self.save()
        return text

    def restore(self, index, text):
        if text in self.items:
            self.items.remove(text)
        self.items.insert(min(index, len(self.items)), text)
        self.save()

    def set_window(self, geometry, pinned):
        self.window = {"geometry": geometry, "pinned": bool(pinned)}
        self.save()


class PinClipApp:
    def __init__(self, root, store):
        self.root = root
        self.store = store
        self._undo = None
        self._status_job = None
        self._labels = []
        self._wrap = 200

        root.title(APP_TITLE)
        root.configure(bg=BG)
        tkfont.nametofont("TkDefaultFont").configure(size=10)
        root.minsize(*MIN_SIZE)
        root.geometry(fit_geometry(store.window.get("geometry"), root.winfo_vrootx(),
                                   root.winfo_vrooty(), root.winfo_vrootwidth(),
                                   root.winfo_vrootheight()))
        root.report_callback_exception = self._on_callback_error
        root.protocol("WM_DELETE_WINDOW", self.close)

        self.pinned = tk.BooleanVar(value=store.window.get("pinned", True) is not False)
        self._build_ui()
        self.apply_pin()
        self.refresh()
        if store.save_failed:
            self.set_status("無法寫入資料檔，這次的內容關掉後不會保留")

    # ---- 介面 ----------------------------------------------------------

    def _build_ui(self):
        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="x", padx=8, pady=(8, 4))
        title_font = tkfont.nametofont("TkDefaultFont").copy()
        title_font.configure(size=11, weight="bold")
        tk.Label(top, text=APP_TITLE, bg=BG, font=title_font).pack(side="left")
        tk.Checkbutton(top, text="釘選", variable=self.pinned, command=self.apply_pin,
                       indicatoron=False, selectcolor="#cfe0fb", bg=BG, padx=10,
                       relief="raised").pack(side="right")

        box = tk.Frame(self.root, bg=BORDER, padx=1, pady=1)
        box.pack(fill="x", padx=8)
        self.input = tk.Text(box, height=4, wrap="word", undo=True, relief="flat",
                             padx=6, pady=4)
        self.input.pack(fill="x")
        self.input.bind("<Control-Return>", self._on_save_key)
        self.input.bind("<Control-KP_Enter>", self._on_save_key)

        actions = tk.Frame(self.root, bg=BG)
        actions.pack(fill="x", padx=8, pady=(4, 6))
        tk.Button(actions, text="貼上並儲存", command=self.paste_and_save).pack(side="left")
        tk.Button(actions, text="儲存", width=6, command=self.save_input).pack(side="right")
        tk.Label(actions, text="Ctrl+Enter", bg=BG, fg=MUTED).pack(side="right", padx=6)

        self.status = tk.Label(self.root, text="", bg=BG, fg=MUTED, anchor="w", padx=10)
        self.status.pack(side="bottom", fill="x", pady=(0, 4))
        self.status.bind("<Button-1>", self._on_status_click)

        area = tk.Frame(self.root, bg=BG)
        area.pack(fill="both", expand=True)
        scroll = tk.Scrollbar(area, orient="vertical")
        scroll.pack(side="right", fill="y")
        self.canvas = tk.Canvas(area, bg=BG, highlightthickness=0, yscrollincrement=20,
                                yscrollcommand=scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scroll.config(command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=BG)
        self._inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.root.bind_all(sequence, self._on_wheel, add="+")

    def refresh(self):
        for child in self.inner.winfo_children():
            child.destroy()
        self._labels = []
        if not self.store.items:
            tk.Label(self.inner, text="還沒有內容。\n在上面貼上文字，按「儲存」。", bg=BG,
                     fg=MUTED, pady=24).pack(fill="x")
            return
        for index, text in enumerate(self.store.items):
            self._add_card(index, text)
        self._update_wrap()

    def _add_card(self, index, text):
        card = tk.Frame(self.inner, bg=CARD_BG, highlightbackground=BORDER,
                        highlightthickness=1)
        card.pack(fill="x", padx=8, pady=3)
        card.columnconfigure(0, weight=1)
        label = tk.Label(card, text=preview(text), bg=CARD_BG, justify="left",
                         anchor="nw", wraplength=self._wrap, cursor="hand2")
        label.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=6)
        self._labels.append(label)
        copy_button = tk.Button(card, text="複製", width=5, fg=ACCENT,
                                command=lambda: self.copy(text, copy_button))
        copy_button.grid(row=0, column=1, padx=(0, 4), pady=6, sticky="n")
        tk.Button(card, text="✕", width=2, relief="flat", fg=MUTED, bg=CARD_BG,
                  command=lambda: self.delete(index)).grid(row=0, column=2, padx=(0, 6),
                                                           pady=6, sticky="n")
        label.bind("<Button-1>", lambda e: self.copy(text, copy_button))

    def _on_canvas_resize(self, event):
        self.canvas.itemconfigure(self._inner_id, width=event.width)
        self._update_wrap()

    def _update_wrap(self):
        """文字的換行寬度 = 視窗寬度扣掉按鈕和各處的邊距，免得字被按鈕蓋住。"""
        if not self._labels:
            return
        card = self._labels[0].master
        buttons = sum(w.winfo_reqwidth() for w in card.winfo_children()
                      if isinstance(w, tk.Button))
        self._wrap = max(80, self.canvas.winfo_width() - buttons - CARD_CHROME)
        for label in self._labels:
            label.configure(wraplength=self._wrap)

    def _on_wheel(self, event):
        if not str(event.widget).startswith(str(self.canvas)):
            return
        if self.canvas.yview() == (0.0, 1.0):
            return
        if event.num == 4:
            step = -1
        elif event.num == 5:
            step = 1
        else:
            step = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(step * 2, "units")

    # ---- 動作 ----------------------------------------------------------

    def apply_pin(self):
        self.root.attributes("-topmost", bool(self.pinned.get()))

    def _on_save_key(self, _event):
        self.save_input()
        return "break"      # 不要在輸入框多插一個換行

    def save_input(self):
        text = self.input.get("1.0", "end-1c")
        if self._add(text):
            self.input.delete("1.0", "end")

    def paste_and_save(self):
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            self.set_status("剪貼簿裡沒有文字")
            return
        self._add(text)

    def _add(self, text):
        if not self.store.add(text):
            self.set_status("沒有內容可以儲存")
            return False
        self._undo = None
        self.refresh()
        self.canvas.yview_moveto(0)
        if self.store.save_failed:
            self.set_status("已加入，但無法寫入資料檔")
        else:
            self.set_status("已儲存")
        return True

    def copy(self, text, button=None):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()      # Windows：讓剪貼簿內容在程式關掉後仍然保留
        self.set_status("已複製")
        if button is not None:
            button.configure(text="已複製 ✓")
            self.root.after(1200, lambda: button.winfo_exists() and button.configure(text="複製"))

    def delete(self, index):
        text = self.store.remove(index)
        self.refresh()
        self.set_status("已刪除　按這裡復原", undo=(index, text), ms=6000)

    def _on_status_click(self, _event):
        if self._undo is None:
            return
        index, text = self._undo
        self.store.restore(index, text)
        self.refresh()
        self.set_status("已復原")

    def set_status(self, text, undo=None, ms=2500):
        if self._status_job is not None:
            self.root.after_cancel(self._status_job)
        self._undo = undo
        self.status.configure(text=text, fg=ACCENT if undo else MUTED,
                              cursor="hand2" if undo else "")
        self._status_job = self.root.after(ms, self._clear_status)

    def _clear_status(self):
        self._status_job = None
        self._undo = None
        self.status.configure(text="", cursor="")

    def close(self):
        self.root.update()      # 讓剛複製的內容留在系統剪貼簿
        self.store.set_window(self.root.geometry(), self.pinned.get())
        self.root.destroy()

    def _on_callback_error(self, exc, value, tb):
        # 用 pythonw 啟動時沒有主控台，錯誤要寫到檔案才看得到
        log = self.store.path.with_name("pinclip_error.log")
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            with open(log, "a", encoding="utf-8") as handle:
                handle.write("".join(traceback.format_exception(exc, value, tb)) + "\n")
        except OSError:
            pass
        self.set_status(f"發生錯誤（{value}），詳見 {log.name}", ms=8000)


def enable_dpi_awareness():
    if sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main():
    enable_dpi_awareness()
    root = tk.Tk()
    PinClipApp(root, ClipStore(default_data_path()))
    root.mainloop()


if __name__ == "__main__":
    main()
