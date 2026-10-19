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
from tkinter import ttk

APP_TITLE = "釘選剪貼簿"
DEFAULT_SIZE = (360, 520)       # 以 96 DPI 的像素計；高 DPI 螢幕會依比例放大
MIN_SIZE = (260, 300)
DEFAULT_GEOMETRY = "%dx%d" % DEFAULT_SIZE

# 配色
SHELL = "#c3c9d4"           # 視窗外框
BG = "#f1f3f7"              # 內容區底色
HEADER = "#262a35"
HEADER_FG = "#ffffff"
HEADER_MUTED = "#a3abbd"
HEADER_HOVER = "#3a4050"
CARD_BG = "#ffffff"
BORDER = "#dce0e8"
TEXT = "#1f2430"
MUTED = "#7a8394"
ACCENT = "#3b6df6"
ACCENT_DARK = "#2a55d3"
ACCENT_SOFT = "#e4ebff"
NEUTRAL = "#e3e6ed"
NEUTRAL_HOVER = "#d5d9e2"
OK = "#1f9d55"
DANGER = "#e5484d"
SCROLL = "#c4c9d4"
SCROLL_HOVER = "#9aa2b2"
WHITE = "#ffffff"

CJK_FONTS = ("Microsoft JhengHei UI", "Microsoft JhengHei", "PingFang TC",
             "Noto Sans CJK TC", "Noto Sans TC", "Noto Sans CJK JP")


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


def want_custom_frame():
    """要不要用自己畫的標題列（沒有系統外框）。

    預設只有 Windows 用：macOS／Linux 的無外框視窗常常拿不到鍵盤焦點，沒辦法在輸入框打字。
    環境變數 PINCLIP_FRAME=custom 或 native 可以強制指定。
    """
    choice = os.environ.get("PINCLIP_FRAME", "").strip().lower()
    if choice in ("custom", "native"):
        return choice == "custom"
    return sys.platform == "win32"


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


def fit_geometry(geometry, vx, vy, vw, vh, default=DEFAULT_GEOMETRY, min_size=MIN_SIZE):
    """檢查上次存的視窗位置：螢幕拔掉或換解析度後，視窗不能跑到看不見的地方。

    (vx, vy, vw, vh) 是整個虛擬桌面的範圍。尺寸不合理就用 default；
    位置看不到（大部分在畫面外）就只保留尺寸，讓系統自己擺。
    """
    match = _GEOMETRY.match(geometry or "")
    if not match:
        return default
    w = max(min_size[0], min(int(match.group(1)), vw))
    h = max(min_size[1], min(int(match.group(2)), vh))
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


class FlatButton(tk.Label):
    """用 Label 做的扁平按鈕：系統原生按鈕又舊又不能配色，這個可以自訂顏色、有滑過效果。"""

    def __init__(self, master, text, command, fg, bg, hover_fg=None, hover_bg=None, **options):
        super().__init__(master, text=text, fg=fg, bg=bg, cursor="hand2", **options)
        self.command = command
        self._hovering = False
        self._flash_job = None
        self._saved = None
        self.set_colors(fg, bg, hover_fg, hover_bg)
        self.bind("<Enter>", lambda e: self._paint(True))
        self.bind("<Leave>", lambda e: self._paint(False))
        self.bind("<ButtonRelease-1>", self._on_release)

    def set_colors(self, fg, bg, hover_fg=None, hover_bg=None):
        self._colors = (fg, bg, hover_fg or fg, hover_bg or bg)
        self._paint(self._hovering)

    def _paint(self, hovering):
        self._hovering = hovering
        fg, bg, hover_fg, hover_bg = self._colors
        self.configure(fg=hover_fg if hovering else fg, bg=hover_bg if hovering else bg)

    def _on_release(self, event):
        # 在按鈕上放開才算按下；按住後把游標拖出去再放開就取消
        if 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            self.invoke()

    def invoke(self):
        self.command()

    def flash(self, text, fg, bg, ms=1200):
        """暫時換成另一組文字和顏色（例如「已複製 ✓」），過一下自動還原。"""
        if self._flash_job is None:
            self._saved = (self.cget("text"), self._colors)
        else:
            self.after_cancel(self._flash_job)
        self.configure(text=text)
        self.set_colors(fg, bg)
        self._flash_job = self.after(ms, self._restore)

    def _restore(self):
        self._flash_job = None
        try:
            text, colors = self._saved
            self.configure(text=text)
            self.set_colors(*colors)
        except tk.TclError:
            pass        # 這顆按鈕已經在重新整理列表時被丟掉了


class Card(tk.Frame):
    """列表裡的一筆內容。"""


class PinClipApp:
    def __init__(self, root, store, custom_frame=False):
        self.root = root
        self.store = store
        self.custom_frame = custom_frame
        self.pinned = store.window.get("pinned", True) is not False
        self.collapsed = False
        self._undo = None
        self._status_job = None
        self._labels = []
        self._wrap = 200
        self._drag = None
        self._resize = None

        self.scale = max(1.0, root.winfo_fpixels("1i") / 96)
        self.min_w, self.min_h = self.px(MIN_SIZE[0]), self.px(MIN_SIZE[1])
        self._border = 1 if custom_frame else 0
        self._make_fonts()
        self._make_styles()

        root.title(APP_TITLE)
        root.configure(bg=SHELL if custom_frame else BG)
        root.minsize(self.min_w, self.min_h)
        if custom_frame:
            root.overrideredirect(True)
        geometry = fit_geometry(
            store.window.get("geometry"), root.winfo_vrootx(), root.winfo_vrooty(),
            root.winfo_vrootwidth(), root.winfo_vrootheight(),
            default="%dx%d" % (self.px(DEFAULT_SIZE[0]), self.px(DEFAULT_SIZE[1])),
            min_size=(self.min_w, self.min_h))
        root.geometry(geometry)
        self._expanded_height = int(geometry.split("x")[1].split("+")[0])
        root.report_callback_exception = self._on_callback_error
        root.protocol("WM_DELETE_WINDOW", self.close)

        self._build_ui()
        self.apply_pin()
        self.refresh()
        if store.save_failed:
            self.set_status("無法寫入資料檔，這次的內容關掉後不會保留", "warn")
        if custom_frame and sys.platform == "win32":
            root.after(80, self._show_in_taskbar)

    def px(self, n):
        return round(n * self.scale)

    # ---- 外觀 ----------------------------------------------------------

    def _make_fonts(self):
        available = set(tkfont.families(self.root))
        family = next((f for f in CJK_FONTS if f in available),
                      tkfont.nametofont("TkDefaultFont").actual("family"))

        def font(size, weight="normal"):
            return tkfont.Font(root=self.root, family=family, size=size, weight=weight)

        self.f_body = font(10)
        self.f_small = font(9)
        self.f_bold = font(10, "bold")
        self.f_small_bold = font(9, "bold")
        self.f_title = font(11, "bold")
        self.f_icon = font(11)

    def _make_styles(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")      # 只有這個主題能完整改色
        name = "Slim.Vertical.TScrollbar"
        style.layout(name, [("Vertical.Scrollbar.trough", {
            "sticky": "ns",
            "children": [("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        style.configure(name, troughcolor=BG, background=SCROLL, bordercolor=BG,
                        lightcolor=SCROLL, darkcolor=SCROLL, relief="flat",
                        arrowsize=self.px(8), gripcount=0)
        style.map(name, background=[("active", SCROLL_HOVER), ("pressed", SCROLL_HOVER)],
                  lightcolor=[("active", SCROLL_HOVER), ("pressed", SCROLL_HOVER)],
                  darkcolor=[("active", SCROLL_HOVER), ("pressed", SCROLL_HOVER)])

    # ---- 介面 ----------------------------------------------------------

    def _build_ui(self):
        P = self.px
        self.shell = tk.Frame(self.root, bg=BG)
        self.shell.pack(fill="both", expand=True, padx=self._border, pady=self._border)
        self._build_header(self.shell)

        self.body = tk.Frame(self.shell, bg=BG)
        self.body.pack(fill="both", expand=True)

        wrap = tk.Frame(self.body, bg=BG)
        wrap.pack(fill="x", padx=P(10), pady=(P(10), 0))
        self.input = tk.Text(
            wrap, height=4, wrap="word", undo=True, relief="flat", bd=0, font=self.f_body,
            bg=CARD_BG, fg=TEXT, insertbackground=TEXT, selectbackground=ACCENT_SOFT,
            selectforeground=TEXT, highlightthickness=1, highlightbackground=BORDER,
            highlightcolor=ACCENT, padx=P(8), pady=P(6))
        self.input.pack(fill="x")
        self.input.bind("<Control-Return>", self._on_save_key)
        self.input.bind("<Control-KP_Enter>", self._on_save_key)
        # 無外框視窗不一定會自動拿到鍵盤焦點，點輸入框時主動要
        self.input.bind("<Button-1>", lambda e: self.root.after_idle(self.input.focus_force))

        actions = tk.Frame(self.body, bg=BG)
        actions.pack(fill="x", padx=P(10), pady=(P(8), 0))
        FlatButton(actions, "貼上並儲存", self.paste_and_save, fg=TEXT, bg=NEUTRAL,
                   hover_bg=NEUTRAL_HOVER, font=self.f_small_bold, padx=P(12),
                   pady=P(5)).pack(side="left")
        FlatButton(actions, "儲存", self.save_input, fg=WHITE, bg=ACCENT,
                   hover_bg=ACCENT_DARK, font=self.f_small_bold, padx=P(18),
                   pady=P(5)).pack(side="right")
        tk.Label(actions, text="Ctrl+Enter", bg=BG, fg=MUTED, font=self.f_small).pack(
            side="right", padx=P(8))

        self.count = tk.Label(self.body, text="", bg=BG, fg=MUTED, font=self.f_small,
                              anchor="w")
        self.count.pack(fill="x", padx=P(12), pady=(P(12), P(4)))

        footer = tk.Frame(self.body, bg=BG)
        footer.pack(side="bottom", fill="x", padx=(P(12), P(4)), pady=(0, P(4)))
        self.status = tk.Label(footer, text="", bg=BG, fg=MUTED, font=self.f_small, anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        self.status.bind("<Button-1>", self._on_status_click)
        if self.custom_frame:
            self._build_grip(footer)

        area = tk.Frame(self.body, bg=BG)
        area.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(area, bg=BG, highlightthickness=0, bd=0,
                                yscrollincrement=P(20), yscrollcommand=self._on_yview)
        self.canvas.pack(fill="both", expand=True)
        # 捲軸浮在右邊，要不要顯示都不會改變卡片寬度
        self.scroll = ttk.Scrollbar(area, orient="vertical", command=self.canvas.yview,
                                    style="Slim.Vertical.TScrollbar")
        self.inner = tk.Frame(self.canvas, bg=BG)
        self._inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.root.bind_all(sequence, self._on_wheel, add="+")

    def _build_header(self, parent):
        P = self.px
        self.header = tk.Frame(parent, bg=HEADER)
        self.header.pack(fill="x")
        title = tk.Label(self.header, text=APP_TITLE, bg=HEADER, fg=HEADER_FG,
                         font=self.f_title, padx=P(12), pady=P(9))
        title.pack(side="left")
        self.close_button = FlatButton(self.header, "✕", self.close, fg=HEADER_MUTED,
                                       bg=HEADER, hover_fg=WHITE, hover_bg=DANGER,
                                       font=self.f_icon, padx=P(14))
        self.close_button.pack(side="right", fill="y")
        self.collapse_button = FlatButton(
            self.header, "—", self.toggle_collapse, fg=HEADER_MUTED, bg=HEADER,
            hover_fg=WHITE, hover_bg=HEADER_HOVER, font=self.f_icon, padx=P(14))
        self.collapse_button.pack(side="right", fill="y")
        self.pin_button = FlatButton(self.header, "", self.toggle_pin, fg=WHITE, bg=ACCENT,
                                     font=self.f_small_bold, padx=P(10), pady=P(2))
        self.pin_button.pack(side="right", padx=P(8), pady=P(8))
        for widget in (self.header, title):
            widget.bind("<Double-Button-1>", lambda e: self.toggle_collapse())
            if self.custom_frame:       # 沒有系統標題列時，拖這一條來移動視窗
                widget.bind("<ButtonPress-1>", self._drag_start)
                widget.bind("<B1-Motion>", self._drag_move)

    def _build_grip(self, parent):
        size = self.px(14)
        self.grip = tk.Canvas(parent, width=size, height=size, bg=BG, highlightthickness=0)
        for cursor in ("size_nw_se", "bottom_right_corner"):     # 前者 Windows 才有，後者 X11 才有
            try:
                self.grip.configure(cursor=cursor)
                break
            except tk.TclError:
                continue
        for i in (4, 8, 12):
            i = self.px(i)
            self.grip.create_line(size, i, i, size, fill=MUTED)
        self.grip.pack(side="right")
        self.grip.bind("<ButtonPress-1>", self._resize_start)
        self.grip.bind("<B1-Motion>", self._resize_move)
        self.grip.bind("<ButtonRelease-1>", self._resize_end)

    def refresh(self):
        P = self.px
        for child in self.inner.winfo_children():
            child.destroy()
        self._labels = []
        count = len(self.store.items)
        self.count.configure(text=f"已儲存 {count} 筆" if count else "")
        if not count:
            empty = tk.Frame(self.inner, bg=BG)
            empty.pack(fill="x", pady=P(30))
            tk.Label(empty, text="還沒有內容", bg=BG, fg=MUTED, font=self.f_bold).pack()
            tk.Label(empty, text="在上方貼上文字，按「儲存」", bg=BG, fg=MUTED,
                     font=self.f_small).pack(pady=(P(4), 0))
            return
        for index, text in enumerate(self.store.items):
            self._add_card(index, text)
        self._update_wrap()

    def _add_card(self, index, text):
        P = self.px
        card = Card(self.inner, bg=CARD_BG, highlightthickness=1, highlightbackground=BORDER,
                    highlightcolor=BORDER)
        card.pack(fill="x", padx=(P(10), P(14)), pady=(0, P(6)))
        card.columnconfigure(0, weight=1)
        label = tk.Label(card, text=preview(text), bg=CARD_BG, fg=TEXT, font=self.f_body,
                         justify="left", anchor="nw", wraplength=self._wrap, cursor="hand2")
        label.grid(row=0, column=0, sticky="nsew", padx=(P(10), P(6)), pady=P(8))
        self._labels.append(label)
        copy_button = FlatButton(
            card, "複製", lambda: self.copy(text, copy_button), fg=ACCENT, bg=ACCENT_SOFT,
            hover_fg=WHITE, hover_bg=ACCENT, font=self.f_small_bold, width=6, pady=P(3))
        copy_button.grid(row=0, column=1, padx=(0, P(4)), pady=P(8), sticky="n")
        FlatButton(card, "✕", lambda: self.delete(index), fg=MUTED, bg=CARD_BG,
                   hover_fg=WHITE, hover_bg=DANGER, font=self.f_small, width=2,
                   pady=P(3)).grid(row=0, column=2, padx=(0, P(8)), pady=P(8), sticky="n")
        label.bind("<Button-1>", lambda e: self.copy(text, copy_button))
        self._watch_hover(card)

    def _watch_hover(self, card):
        """游標在卡片上（含裡面的按鈕）時外框變色。"""
        def update(_event=None):
            try:
                x, y = card.winfo_pointerxy()
                under = card.winfo_containing(x, y)
            except (KeyError, tk.TclError):
                return
            inside = under is not None and str(under).startswith(str(card))
            card.configure(highlightbackground=ACCENT if inside else BORDER)

        for widget in (card, *card.winfo_children()):
            widget.bind("<Enter>", update, add="+")
            widget.bind("<Leave>", update, add="+")

    def _on_canvas_resize(self, event):
        self.canvas.itemconfigure(self._inner_id, width=event.width)
        self._update_wrap()

    def _update_wrap(self):
        """文字的換行寬度 = 視窗寬度扣掉按鈕和各處的邊距，免得字被按鈕蓋住。"""
        if not self._labels:
            return
        P = self.px
        card = self._labels[0].master
        buttons = sum(w.winfo_reqwidth() for w in card.winfo_children()
                      if isinstance(w, FlatButton))
        chrome = P(10) + P(14) + 2 + P(10) + P(6) + P(4) + P(8)
        self._wrap = max(80, self.canvas.winfo_width() - buttons - chrome)
        for label in self._labels:
            label.configure(wraplength=self._wrap)

    def _on_yview(self, first, last):
        self.scroll.set(first, last)
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.scroll.place_forget()
        elif not self.scroll.winfo_manager():
            self.scroll.place(relx=1.0, rely=0.0, relheight=1.0, anchor="ne")

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

    # ---- 視窗：釘選、縮小、移動、調整大小 ---------------------------------

    def apply_pin(self):
        self.root.attributes("-topmost", self.pinned)
        if self.pinned:
            self.pin_button.configure(text="已釘選")
            self.pin_button.set_colors(WHITE, ACCENT, WHITE, ACCENT_DARK)
        else:
            self.pin_button.configure(text="未釘選")
            self.pin_button.set_colors(HEADER_MUTED, HEADER_HOVER, WHITE, "#4a5166")

    def toggle_pin(self):
        self.pinned = not self.pinned
        self.apply_pin()

    def toggle_collapse(self):
        """縮小：只剩標題列（還是釘在最上層）；再按一次還原。"""
        root = self.root
        if not self.collapsed:
            if root.winfo_ismapped():
                self._expanded_height = root.winfo_height()
            self.body.pack_forget()
            root.update_idletasks()
            height = self.header.winfo_reqheight() + 2 * self._border
            root.minsize(self.min_w, height)
            root.geometry(f"{root.winfo_width()}x{height}")
            root.resizable(True, False)
            self.collapse_button.configure(text="□")
            if self.custom_frame:
                self.grip.pack_forget()
        else:
            root.resizable(True, True)
            root.minsize(self.min_w, self.min_h)
            root.geometry(f"{root.winfo_width()}x{self._expanded_height}")
            self.body.pack(fill="both", expand=True)
            self.collapse_button.configure(text="—")
        self.collapsed = not self.collapsed

    def _drag_start(self, event):
        self._drag = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag_move(self, event):
        if self._drag:
            self.root.geometry(f"+{event.x_root - self._drag[0]}+{event.y_root - self._drag[1]}")

    def _resize_start(self, event):
        self._resize = (event.x_root, event.y_root, self.root.winfo_width(),
                        self.root.winfo_height())

    def _resize_move(self, event):
        if self._resize:
            x0, y0, w0, h0 = self._resize
            width = max(self.min_w, w0 + event.x_root - x0)
            height = max(self.min_h, h0 + event.y_root - y0)
            self.root.geometry(f"{width}x{height}")

    def _resize_end(self, _event):
        self._resize = None
        self._expanded_height = self.root.winfo_height()

    def _show_in_taskbar(self):
        """無外框的視窗預設不會出現在工作列；Windows 上補回去，沒釘選又被蓋住時才找得回來。"""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(self.root.winfo_id())
            style = user32.GetWindowLongW(hwnd, -20)                  # GWL_EXSTYLE
            style = (style & ~0x00000080) | 0x00040000                # 去掉 TOOLWINDOW、加上 APPWINDOW
            user32.SetWindowLongW(hwnd, -20, style)
            self.root.withdraw()
            self.root.after(30, self._reshow)
        except Exception:
            pass

    def _reshow(self):
        self.root.deiconify()
        self.apply_pin()

    # ---- 動作 ----------------------------------------------------------

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
            self.set_status("剪貼簿裡沒有文字", "warn")
            return
        self._add(text)

    def _add(self, text):
        if not self.store.add(text):
            self.set_status("沒有內容可以儲存", "warn")
            return False
        self.refresh()
        self.canvas.yview_moveto(0)
        if self.store.save_failed:
            self.set_status("已加入，但無法寫入資料檔", "warn")
        else:
            self.set_status("已儲存", "ok")
        return True

    def copy(self, text, button=None):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()      # Windows：讓剪貼簿內容在程式關掉後仍然保留
        self.set_status("已複製", "ok")
        if button is not None:
            button.flash("已複製 ✓", WHITE, OK)

    def delete(self, index):
        text = self.store.remove(index)
        self.refresh()
        self.set_status("已刪除　按這裡復原", "undo", undo=(index, text), ms=6000)

    def _on_status_click(self, _event):
        if self._undo is None:
            return
        index, text = self._undo
        self.store.restore(index, text)
        self.refresh()
        self.set_status("已復原", "ok")

    def set_status(self, text, tone="muted", undo=None, ms=2500):
        if self._status_job is not None:
            self.root.after_cancel(self._status_job)
        self._undo = undo
        color = {"ok": OK, "warn": DANGER, "undo": ACCENT}.get(tone, MUTED)
        self.status.configure(text=text, fg=color, cursor="hand2" if undo else "")
        self._status_job = self.root.after(ms, self._clear_status)

    def _clear_status(self):
        self._status_job = None
        self._undo = None
        self.status.configure(text="", cursor="")

    def _geometry_for_save(self):
        geometry = self.root.geometry()
        match = _GEOMETRY.match(geometry)
        if self.collapsed and match and match.group(3) is not None:
            return f"{match.group(1)}x{self._expanded_height}+{match.group(3)}+{match.group(4)}"
        return geometry

    def close(self):
        self.root.update()      # 讓剛複製的內容留在系統剪貼簿
        self.store.set_window(self._geometry_for_save(), self.pinned)
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
        self.set_status(f"發生錯誤（{value}），詳見 {log.name}", "warn", ms=8000)


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
    PinClipApp(root, ClipStore(default_data_path()), custom_frame=want_custom_frame())
    root.mainloop()


if __name__ == "__main__":
    main()
