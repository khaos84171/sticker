"""剪貼簿：永遠顯示在最上層的小視窗，只保存「你自己貼進來」的文字，一鍵複製。

不會監看系統剪貼簿：只有你自己貼進輸入框、按「儲存」（Ctrl+Enter）的文字才會加入。
資料放在使用者資料夾（Windows 是 %APPDATA%\\pinclip），不放在程式資料夾，避免被 git 收進去。
"""
import json
import math
import os
import re
import shutil
import sys
import time
import traceback
import zlib
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk

APP_TITLE = "剪貼簿"
DEFAULT_SIZE = (360, 520)       # 以 96 DPI 的像素計；高 DPI 螢幕會依比例放大
MIN_SIZE = (260, 300)
DEFAULT_GEOMETRY = "%dx%d" % DEFAULT_SIZE

# 配色：馬卡龍淡色系
SHELL = "#ead9ee"           # 視窗外框（淡紫）
BG = "#fffaf5"              # 內容區底色（奶油）
HEADER = "#fbdce7"          # 標題列（草莓粉）
HEADER_FG = "#6e4a5f"
HEADER_MUTED = "#a5899b"
HEADER_HOVER = "#f6c6d8"
CLOSE_HOVER = "#ff9fb7"
PIN_ON_BG = "#dccdf7"       # 釘選中的底色（薰衣草）
PIN_ON_FG = "#5b3f9a"
CARD_BG = "#ffffff"
BORDER = "#f0e4ee"
HOVER_BORDER = "#cdb8f2"
DRAG_BORDER = "#a98be8"
TEXT = "#4b4458"
MUTED = "#a198ad"
PRIMARY = "#cdb8f6"         # 「儲存」（薰衣草）
PRIMARY_HOVER = "#bca2f0"
PRIMARY_FG = "#4a2f7a"
COPY_BG = "#d4ebff"         # 複製（天空藍）
COPY_HOVER = "#b9dcfb"
COPY_FG = "#386d9c"
COPY_DONE_BG = "#bdf0d6"
COPY_DONE_FG = "#1f7a52"
DELETE_FG = "#c0b4c9"
DELETE_HOVER_BG = "#ffd3df"
DELETE_HOVER_FG = "#c0405f"
HANDLE = "#d6cce0"
OK = "#2f9e72"
WARN = "#d6456a"
UNDO = "#7c5cd6"
SCROLL = "#e4d8ec"
SCROLL_HOVER = "#cdb8dc"
# 每張卡片左邊的色條，依內容固定選色（重開、換順序都不會變）
STRIPES = ("#ffc8dd", "#ffdab9", "#fff1a8", "#b9f0d6", "#bde0fe", "#d9c7f5")

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


# 拖曳排序時的邊緣自動捲動（像素以 96 DPI 計）
EDGE_ZONE = 32          # 離列表上下緣多近算「在邊緣」
EDGE_MAX_STEP = 10      # 游標在邊緣上或超出邊緣時，每次最多捲幾個像素
EDGE_DELAY = 0.4        # 停在邊緣多久（秒）才開始捲
AUTOSCROLL_MS = 30


def edge_scroll_step(y, height, zone, max_step):
    """游標在列表裡的高度 y（0 是列表上緣）→ 這一次要捲幾個像素：負的往上、正的往下、0 不捲。

    剛進入邊緣區只捲 1 像素，到列表邊緣上約一半速度，游標拖出列表外才到最快。
    """
    if y < zone:
        depth = (zone - y) / zone
        sign = -1
    elif y > height - zone:
        depth = (y - (height - zone)) / zone
        sign = 1
    else:
        return 0
    return sign * max(1, round(min(depth, 2.0) * max_step / 2))


# 無外框視窗的縮放：視窗最外面一圈邊框（淡紫色）就是拖曳縮放的地方
EDGE = 5                # 邊框厚度（像素，96 DPI）
EDGE_CORNER = 18        # 邊框上靠近角落的這一段長度算「角落」，可以斜著拉
RESIZE_CURSORS = {      # 各系統的游標名稱不同：Windows 是前面的，X11 是後面的
    "n": ("size_ns", "sb_v_double_arrow"), "s": ("size_ns", "sb_v_double_arrow"),
    "e": ("size_we", "sb_h_double_arrow"), "w": ("size_we", "sb_h_double_arrow"),
    "nw": ("size_nw_se", "top_left_corner"), "se": ("size_nw_se", "bottom_right_corner"),
    "ne": ("size_ne_sw", "top_right_corner"), "sw": ("size_ne_sw", "bottom_left_corner"),
}


def edge_at(x, y, width, height, border, corner):
    """視窗內座標 (x, y) 在哪個縮放邊：n s e w nw ne sw se，不在邊框上回傳 None。"""
    left, right = x < border, x >= width - border
    top, bottom = y < border, y >= height - border
    if not (left or right or top or bottom):
        return None
    on_side = left or right
    on_end = top or bottom
    vertical = ("n" if top or (on_side and y < corner)
                else "s" if bottom or (on_side and y >= height - corner) else "")
    horizontal = ("w" if left or (on_end and x < corner)
                  else "e" if right or (on_end and x >= width - corner) else "")
    return (vertical + horizontal) or None


def stripe_color(text):
    return STRIPES[zlib.crc32(text.encode("utf-8")) % len(STRIPES)]


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

    def move(self, src, dst):
        """把第 src 筆移到第 dst 的位置（手動排序）。"""
        if src == dst:
            return
        self.items.insert(dst, self.items.pop(src))
        self.save()

    def set_window(self, geometry, pinned):
        self.window = {"geometry": geometry, "pinned": bool(pinned)}
        self.save()


# ---- 圖標與按鈕 -------------------------------------------------------------
# 圖標都是用 Canvas 畫的線條，不靠字型：換電腦、換字型都長一樣，也不會有 emoji 變成方框的問題。

def rounded_rect(canvas, x1, y1, x2, y2, r, **options):
    points = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
              x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(points, smooth=True, **options)


def draw_icon(canvas, name, ox, oy, size, color, fill, width):
    """在 (ox, oy) 起、邊長 size 的方框裡畫圖標。座標以 16×16 為準再縮放。fill 是按鈕底色。"""
    unit = size / 16

    def pt(x, y):
        return ox + x * unit, oy + y * unit

    def line(*points):
        coords = [c for p in points for c in pt(*p)]
        canvas.create_line(*coords, fill=color, width=width, capstyle="round",
                           joinstyle="round")

    def rect(x1, y1, x2, y2, inside=""):
        canvas.create_rectangle(*pt(x1, y1), *pt(x2, y2), outline=color, fill=inside,
                                width=width)

    if name == "minus":
        line((3, 8), (13, 8))
    elif name == "close":
        line((4, 4), (12, 12))
        line((12, 4), (4, 12))
    elif name == "check":
        line((3, 8.5), (6.5, 12), (13, 4.5))
    elif name == "copy":
        rect(6, 2.5, 13.5, 10.5)
        rect(2.5, 5.5, 10, 13.5, inside=fill)
    elif name in ("pin", "pin_off"):
        # 圖釘：釘選中是直立實心；沒釘選是歪倒的空心
        head = [(5, 2), (11, 2), (11, 4), (10, 4.5), (10, 8), (12, 10), (12, 11),
                (4, 11), (4, 10), (6, 8), (6, 4.5), (5, 4)]
        needle = [(8, 11), (8, 15)]
        if name == "pin_off":
            angle = math.radians(45)
            sin, cos = math.sin(angle), math.cos(angle)

            def rotate(p):
                dx, dy = p[0] - 8, p[1] - 8
                return 8 + dx * cos - dy * sin, 8 + dx * sin + dy * cos

            head, needle = [rotate(p) for p in head], [rotate(p) for p in needle]
        coords = [c for p in head for c in pt(*p)]
        canvas.create_polygon(*coords, fill=color if name == "pin" else "", outline=color,
                              width=width, joinstyle="round")
        line(*needle)


def set_cursor(widget, *names):
    """游標名稱各系統不一樣（Windows 有 size_nw_se、X11 有 bottom_right_corner…），用第一個能用的。"""
    for name in names:
        try:
            widget.configure(cursor=name)
            return
        except tk.TclError:
            continue


class _Clickable:
    """按鈕共用的行為：滑過變色、在按鈕上放開才算按下、暫時換成另一個樣子（flash）。"""

    def _init_click(self, command, fg, bg, hover_fg, hover_bg):
        self.command = command
        self._hovering = False
        self._flash_job = None
        self._saved = None
        self.bind("<Enter>", lambda e: self._paint(True))
        self.bind("<Leave>", lambda e: self._paint(False))
        self.bind("<ButtonRelease-1>", self._on_release)
        self.set_colors(fg, bg, hover_fg, hover_bg)

    def set_colors(self, fg, bg, hover_fg=None, hover_bg=None):
        self._colors = (fg, bg, hover_fg or fg, hover_bg or bg)
        self._paint(self._hovering)

    def _paint(self, hovering):
        self._hovering = hovering
        fg, bg, hover_fg, hover_bg = self._colors
        self._render(hover_fg if hovering else fg, hover_bg if hovering else bg)

    def _on_release(self, event):
        # 在按鈕上放開才算按下；按住後把游標拖出去再放開就取消
        if 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            self.invoke()

    def invoke(self):
        self.command()

    def flash(self, content, fg, bg, ms=1200):
        """暫時換成另一組內容和顏色（例如打勾的「已複製」），過一下自動還原。"""
        if self._flash_job is None:
            self._saved = (self._get_content(), self._colors)
        else:
            self.after_cancel(self._flash_job)
        self._set_content(content)
        self.set_colors(fg, bg)
        self._flash_job = self.after(ms, self._restore)

    def _restore(self):
        self._flash_job = None
        try:
            content, colors = self._saved
            self._set_content(content)
            self.set_colors(*colors)
        except tk.TclError:
            pass        # 這顆按鈕已經在重新整理列表時被丟掉了


class FlatButton(_Clickable, tk.Label):
    """文字按鈕：用 Label 做的扁平按鈕（系統原生按鈕又舊又不能配色）。"""

    def __init__(self, master, text, command, fg, bg, hover_fg=None, hover_bg=None, **options):
        tk.Label.__init__(self, master, text=text, fg=fg, bg=bg, cursor="hand2", **options)
        self._init_click(command, fg, bg, hover_fg, hover_bg)

    def _render(self, fg, bg):
        self.configure(fg=fg, bg=bg)

    def _get_content(self):
        return self.cget("text")

    def _set_content(self, text):
        self.configure(text=text)


class IconButton(_Clickable, tk.Canvas):
    """圖標按鈕：圖標用 draw_icon 畫；radius > 0 時是圓角底色，surface 是圓角外面露出的顏色。"""

    def __init__(self, master, icon, command, width, height, icon_size, fg, bg,
                 hover_fg=None, hover_bg=None, surface=None, radius=0, line=1.6):
        tk.Canvas.__init__(self, master, width=width, height=height, bg=surface or bg,
                           highlightthickness=0, bd=0, cursor="hand2")
        self.icon = icon
        self._shape = (width, height, icon_size, radius, line)
        self._current = (fg, bg)
        self.bind("<Configure>", lambda e: self._redraw())
        self._init_click(command, fg, bg, hover_fg, hover_bg)

    def _render(self, fg, bg):
        self._current = (fg, bg)
        self._redraw()

    def _get_content(self):
        return self.icon

    def _set_content(self, icon):
        self.icon = icon

    def _redraw(self):
        fg, bg = self._current
        req_w, req_h, size, radius, line = self._shape
        w = self.winfo_width() if self.winfo_width() > 1 else req_w
        h = self.winfo_height() if self.winfo_height() > 1 else req_h
        self.delete("all")
        if radius:
            rounded_rect(self, 0, 0, w - 1, h - 1, radius, fill=bg, outline=bg)
        else:
            self.create_rectangle(0, 0, w, h, fill=bg, outline=bg)
        draw_icon(self, self.icon, (w - size) / 2, (h - size) / 2, size, fg, bg, line)


class Card(tk.Frame):
    """列表裡的一筆內容。text 是這筆的文字；hover_update 重新判斷游標在不在卡片上。"""

    text = ""
    hover_update = None


class PinClipApp:
    def __init__(self, root, store, custom_frame=False):
        self.root = root
        self.store = store
        self.custom_frame = custom_frame
        self.pinned = store.window.get("pinned", True) is not False
        self._minimized = False     # 無外框視窗縮到工作列期間為 True（見 minimize）
        self._saved_geometry = ""
        self._undo = None
        self._status_job = None
        self._labels = []
        self._cards = []            # 畫面上卡片的順序（拖曳排序時會即時改變）
        self._wrap = 200
        self._drag = None           # 拖曳移動視窗
        self._resize_drag = None    # 正在縮放視窗：(邊, 按下的位置, 視窗原本的位置和大小)
        self._edge_cursor = None    # 游標目前停在哪個縮放邊
        self._press_pos = None      # 按下卡片的位置；移動超過幾個像素才算拖曳
        self._drag_card = None      # 正在被拖曳排序的卡片
        self._autoscroll_job = None
        self._edge_since = None     # 游標開始停在列表邊緣的時間

        self.scale = max(1.0, root.winfo_fpixels("1i") / 96)
        self.min_w, self.min_h = self.px(MIN_SIZE[0]), self.px(MIN_SIZE[1])
        self._border = self.px(EDGE) if custom_frame else 0
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
        root.report_callback_exception = self._on_callback_error
        root.protocol("WM_DELETE_WINDOW", self.close)

        self._build_ui()
        if custom_frame:
            self._bind_edges()
            root.bind("<Map>", self._on_map, add="+")
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
            bg=CARD_BG, fg=TEXT, insertbackground=TEXT, selectbackground=PRIMARY,
            selectforeground=PRIMARY_FG, highlightthickness=1, highlightbackground=BORDER,
            highlightcolor=PRIMARY_HOVER, padx=P(8), pady=P(6))
        self.input.pack(fill="x")
        self.input.bind("<Control-Return>", self._on_save_key)
        self.input.bind("<Control-KP_Enter>", self._on_save_key)
        # 無外框視窗不一定會自動拿到鍵盤焦點，點輸入框時主動要
        self.input.bind("<Button-1>", lambda e: self.root.after_idle(self.input.focus_force))

        actions = tk.Frame(self.body, bg=BG)
        actions.pack(fill="x", padx=P(10), pady=(P(8), 0))
        tk.Label(actions, text="Ctrl+Enter 也可以儲存", bg=BG, fg=MUTED,
                 font=self.f_small).pack(side="left")
        FlatButton(actions, "儲存", self.save_input, fg=PRIMARY_FG, bg=PRIMARY,
                   hover_bg=PRIMARY_HOVER, font=self.f_small_bold, padx=P(18),
                   pady=P(5)).pack(side="right")

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
        # yscrollincrement=1：捲動單位是 1 像素。設成更大的值時，Tk 會把位置湊成它的倍數，
        # 自動捲動每次只捲幾個像素就會被湊回原位而完全不動。
        self.canvas = tk.Canvas(area, bg=BG, highlightthickness=0, bd=0, yscrollincrement=1,
                                yscrollcommand=self._on_yview)
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
                         font=self.f_title, padx=P(14), pady=P(10))
        title.pack(side="left")

        def header_button(icon, command, **options):
            return IconButton(self.header, icon, command, width=P(40), height=P(38),
                              icon_size=P(14), fg=HEADER_MUTED, bg=HEADER, hover_fg=HEADER_FG,
                              hover_bg=HEADER_HOVER, line=1.6 * self.scale, **options)

        self.close_button = header_button("close", self.close)
        self.close_button.set_colors(HEADER_MUTED, HEADER, HEADER_FG, CLOSE_HOVER)
        self.close_button.pack(side="right", fill="y")
        self.minimize_button = header_button("minus", self.minimize)
        self.minimize_button.pack(side="right", fill="y")
        self.pin_button = IconButton(self.header, "pin", self.toggle_pin, width=P(30),
                                     height=P(30), icon_size=P(16), fg=PIN_ON_FG, bg=PIN_ON_BG,
                                     surface=HEADER, radius=P(9), line=1.5 * self.scale)
        self.pin_button.pack(side="right", padx=P(6), pady=P(4))
        if self.custom_frame:           # 沒有系統標題列時，拖這一條來移動視窗
            for widget in (self.header, title):
                widget.bind("<ButtonPress-1>", self._drag_start)
                widget.bind("<B1-Motion>", self._drag_move)

    def _build_grip(self, parent):
        size = self.px(14)
        self.grip = tk.Canvas(parent, width=size, height=size, bg=BG, highlightthickness=0)
        set_cursor(self.grip, "size_nw_se", "bottom_right_corner")
        for i in (4, 8, 12):
            i = self.px(i)
            self.grip.create_line(size, i, i, size, fill=HANDLE)
        self.grip.pack(side="right")
        # 按下時開始縮放；之後的移動和放開由 _bind_edges 的視窗層級綁定處理
        self.grip.bind("<ButtonPress-1>", lambda e: self._start_resize("se", e))

    def refresh(self):
        P = self.px
        self._stop_drag()
        for child in self.inner.winfo_children():
            child.destroy()
        self._labels = []
        self._cards = []
        count = len(self.store.items)
        hint = "　拖曳卡片可以調整順序" if count > 1 else ""
        self.count.configure(text=f"已儲存 {count} 筆{hint}" if count else "")
        if not count:
            empty = tk.Frame(self.inner, bg=BG)
            empty.pack(fill="x", pady=P(30))
            tk.Label(empty, text="還沒有內容", bg=BG, fg=MUTED, font=self.f_bold).pack()
            tk.Label(empty, text="在上方貼上文字，按「儲存」", bg=BG, fg=MUTED,
                     font=self.f_small).pack(pady=(P(4), 0))
            return
        for text in self.store.items:
            self._add_card(text)
        self._update_wrap()

    def _pads(self):
        """卡片裡各元件左右的留白。換行寬度的計算也用同一份，兩邊才不會對不上。"""
        P = self.px
        return {"card": (P(10), P(14)), "handle": (P(8), 0), "label": (P(6), P(6)),
                "copy": (0, P(4)), "delete": (0, P(8))}

    def _add_card(self, text):
        P = self.px
        pads = self._pads()
        card = Card(self.inner, bg=CARD_BG, highlightthickness=1, highlightbackground=BORDER,
                    highlightcolor=BORDER)
        card.text = text
        card.pack(fill="x", padx=pads["card"], pady=(0, P(6)))
        card.columnconfigure(2, weight=1)
        label = tk.Label(card, text=preview(text), bg=CARD_BG, fg=TEXT, font=self.f_body,
                         justify="left", anchor="nw", wraplength=self._wrap, cursor="hand2")
        label.grid(row=0, column=2, sticky="nsew", padx=pads["label"], pady=P(8))
        self._labels.append(label)

        stripe = tk.Frame(card, bg=stripe_color(text), width=P(5))
        stripe.grid(row=0, column=0, sticky="ns")
        handle = tk.Canvas(card, width=P(12), height=P(24), bg=CARD_BG, highlightthickness=0)
        set_cursor(handle, "fleur", "size")
        radius = max(1.0, 1.1 * self.scale)
        for cx in (P(3), P(9)):
            for cy in (P(5), P(12), P(19)):
                handle.create_oval(cx - radius, cy - radius, cx + radius, cy + radius,
                                   fill=HANDLE, outline=HANDLE)
        handle.grid(row=0, column=1, sticky="n", padx=pads["handle"], pady=(P(10), 0))

        copy_button = IconButton(
            card, "copy", lambda: self.copy(text, copy_button), width=P(32), height=P(28),
            icon_size=P(15), fg=COPY_FG, bg=COPY_BG, hover_bg=COPY_HOVER, surface=CARD_BG,
            radius=P(8), line=1.5 * self.scale)
        copy_button.grid(row=0, column=3, padx=pads["copy"], pady=P(8), sticky="n")
        delete_button = IconButton(
            card, "close", lambda: self.delete(text), width=P(26), height=P(28),
            icon_size=P(12), fg=DELETE_FG, bg=CARD_BG, hover_fg=DELETE_HOVER_FG,
            hover_bg=DELETE_HOVER_BG, radius=P(8), line=1.5 * self.scale)
        delete_button.grid(row=0, column=4, padx=pads["delete"], pady=P(8), sticky="n")

        # 按住卡片（文字、色條、把手、空白處）拖動就是排序；沒移動就放開，點文字＝複製
        for widget, click in ((label, lambda: self.copy(text, copy_button)), (card, None),
                              (stripe, None), (handle, None)):
            self._bind_drag(widget, card, click)
        self._watch_hover(card)
        self._cards.append(card)

    def _watch_hover(self, card):
        """游標在卡片上（含裡面的按鈕）時外框變色；正在被拖曳的卡片維持拖曳的顏色。"""
        def update(_event=None):
            if card is self._drag_card:
                return
            try:
                x, y = card.winfo_pointerxy()
                under = card.winfo_containing(x, y)
            except (KeyError, tk.TclError):
                return
            inside = under is not None and str(under).startswith(str(card))
            card.configure(highlightbackground=HOVER_BORDER if inside else BORDER)

        card.hover_update = update
        for widget in (card, *card.winfo_children()):
            widget.bind("<Enter>", update, add="+")
            widget.bind("<Leave>", update, add="+")

    # ---- 拖曳排序 --------------------------------------------------------

    def _bind_drag(self, widget, card, click):
        widget.bind("<ButtonPress-1>", lambda e: self._card_press(e))
        widget.bind("<B1-Motion>", lambda e: self._card_motion(e, card))
        widget.bind("<ButtonRelease-1>", lambda e: self._card_release(click))

    def _card_press(self, event):
        self._press_pos = (event.x_root, event.y_root)

    def _card_motion(self, event, card):
        if self._press_pos is None:
            return
        if self._drag_card is None:
            moved = max(abs(event.x_root - self._press_pos[0]),
                        abs(event.y_root - self._press_pos[1]))
            if moved < self.px(5):
                return          # 還只是點一下，手抖的幾個像素不算拖曳
            self._drag_card = card
            card.configure(highlightbackground=DRAG_BORDER)
            self._autoscroll()
        self._reorder_to(event.y_root)

    def _card_release(self, click):
        if self._drag_card is not None:
            self._drop()
        elif click is not None and self._press_pos is not None:
            click()
        self._press_pos = None

    def _reorder_to(self, y_root):
        """依游標高度，把拖曳中的卡片即時換到對應位置（其他卡片會讓開）。"""
        card = self._drag_card
        y = y_root - self.inner.winfo_rooty()
        others = [c for c in self._cards if c is not card]
        target = sum(1 for c in others if c.winfo_y() + c.winfo_height() / 2 < y)
        if target == self._cards.index(card):
            return
        self._cards.remove(card)
        self._cards.insert(target, card)
        if target + 1 < len(self._cards):
            card.pack_configure(before=self._cards[target + 1])
        else:
            card.pack_configure(after=self._cards[target - 1])
        self.inner.update_idletasks()

    def _autoscroll(self):
        """拖到列表上緣或下緣時，列表慢慢往那邊捲，這樣長列表也能拖到很遠的位置。

        游標要在邊緣停留一下才開始捲（路過不算），而且越靠近邊緣捲得越快，
        否則把卡片往下拖一點點碰到邊緣，整個列表就會衝到最底。
        """
        if self._drag_card is None:
            return
        pointer_y = self.canvas.winfo_pointery()
        step = edge_scroll_step(pointer_y - self.canvas.winfo_rooty(),
                                self.canvas.winfo_height(), self.px(EDGE_ZONE),
                                self.px(EDGE_MAX_STEP))
        now = time.monotonic()
        if step == 0:
            self._edge_since = None
        else:
            if self._edge_since is None:
                self._edge_since = now
            if now - self._edge_since >= EDGE_DELAY and self._scroll_by(step):
                self._reorder_to(pointer_y)
        self._autoscroll_job = self.root.after(AUTOSCROLL_MS, self._autoscroll)

    def _scroll_by(self, pixels):
        """列表往下捲 pixels 像素（負的是往上）。已經到頭了就回傳 False。"""
        bbox = self.canvas.bbox("all")
        if not bbox:
            return False
        total, view = bbox[3] - bbox[1], self.canvas.winfo_height()
        top = self.canvas.canvasy(0)
        target = max(0, min(total - view, top + pixels))
        if total <= view or target == top:
            return False
        self.canvas.yview_moveto(target / total)
        return True

    def _stop_drag(self):
        if self._autoscroll_job is not None:
            self.root.after_cancel(self._autoscroll_job)
            self._autoscroll_job = None
        self._edge_since = None
        self._drag_card = None
        self._press_pos = None

    def _drop(self):
        card = self._drag_card
        self._stop_drag()
        src = self.store.items.index(card.text)
        dst = self._cards.index(card)
        card.configure(highlightbackground=BORDER)
        if card.hover_update:
            card.hover_update()
        if src == dst:
            return
        self.store.move(src, dst)
        if self.store.save_failed:
            self.set_status("已調整順序，但無法寫入資料檔", "warn")
        else:
            self.set_status("已調整順序", "ok")

    # ---- 捲動與換行 ------------------------------------------------------

    def _on_canvas_resize(self, event):
        self.canvas.itemconfigure(self._inner_id, width=event.width)
        self._update_wrap()

    def _update_wrap(self):
        """文字的換行寬度 = 視窗寬度扣掉其他元件和各處的留白，免得字被按鈕蓋住。"""
        if not self._labels:
            return
        label = self._labels[0]
        card = label.master
        fixed = sum(w.winfo_reqwidth() for w in card.winfo_children() if w is not label)
        margins = sum(a + b for a, b in self._pads().values()) + 2
        self._wrap = max(80, self.canvas.winfo_width() - fixed - margins)
        for each in self._labels:
            each.configure(wraplength=self._wrap)

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
        self.canvas.yview_scroll(step * self.px(40), "units")      # 滾輪每格 40 像素

    # ---- 視窗：釘選、最小化、移動、調整大小 -------------------------------

    def apply_pin(self):
        self.root.attributes("-topmost", self.pinned)
        if self.pinned:
            self.pin_button.icon = "pin"
            self.pin_button.set_colors(PIN_ON_FG, PIN_ON_BG, PIN_ON_FG, "#cdbbf3")
        else:
            self.pin_button.icon = "pin_off"
            self.pin_button.set_colors(HEADER_MUTED, HEADER, HEADER_FG, HEADER_HOVER)

    def toggle_pin(self):
        self.pinned = not self.pinned
        self.apply_pin()

    def minimize(self):
        """縮到工作列，跟一般視窗一樣；從工作列點一下就還原。"""
        root = self.root
        if self.custom_frame:
            # 無外框（overrideredirect）的視窗沒辦法最小化：先換回有外框的狀態再縮下去，
            # 等使用者從工作列點開時（見 _on_map）再換回無外框。
            self._minimized = True
            self._saved_geometry = root.geometry()
            self._set_borderless(False)
        root.iconify()

    def _set_borderless(self, borderless):
        """換成無外框／有外框。X11 上要先把視窗藏起來、換好再顯示才會生效；Windows 直接換就行。"""
        root = self.root
        if sys.platform != "win32":
            root.withdraw()
        root.update_idletasks()
        root.overrideredirect(borderless)

    def _on_map(self, event):
        """視窗被顯示出來。如果是從工作列還原的，換回無外框。"""
        if event.widget is not self.root or not self._minimized:
            return
        if self.root.state() == "iconic":
            return          # 換成有外框時 Tk 也會送一次 Map，那不是還原
        self._minimized = False
        root = self.root
        self._set_borderless(True)
        root.deiconify()
        root.geometry(self._saved_geometry)     # 有外框和無外框的位置會差一個標題列，換回來要擺回原處
        self.apply_pin()
        if sys.platform == "win32":
            root.after(30, self._show_in_taskbar)       # 換回無外框後，工作列按鈕要再補一次

    def _drag_start(self, event):
        self._drag = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag_move(self, event):
        if self._drag:
            self.root.geometry(f"+{event.x_root - self._drag[0]}+{event.y_root - self._drag[1]}")

    # ---- 拖曳邊框縮放視窗 --------------------------------------------------

    def _bind_edges(self):
        """沒有系統外框就沒有系統的縮放功能，自己做：滑過邊框變游標、按住拖曳縮放。

        邊框是視窗本身沒被內容蓋住的那一圈，所以事件的 widget 就是視窗本身；
        子元件的事件也會經過這裡（視窗是它們的 bindtags 之一），要用 event.widget 分辨。
        """
        root = self.root
        root.bind("<Motion>", self._edge_hover, add="+")
        root.bind("<Leave>", self._edge_leave, add="+")
        root.bind("<ButtonPress-1>", self._edge_press, add="+")
        root.bind("<B1-Motion>", self._edge_motion, add="+")
        root.bind("<ButtonRelease-1>", self._edge_release, add="+")

    def _edge_zone(self, event):
        if event.widget is not self.root:
            return None
        return edge_at(event.x, event.y, self.root.winfo_width(), self.root.winfo_height(),
                       self._border, self.px(EDGE_CORNER))

    def _set_edge_cursor(self, zone):
        if zone == self._edge_cursor:
            return
        self._edge_cursor = zone
        if zone:
            set_cursor(self.root, *RESIZE_CURSORS[zone])
        else:
            self.root.configure(cursor="")

    def _edge_hover(self, event):
        if self._resize_drag is None:
            self._set_edge_cursor(self._edge_zone(event))

    def _edge_leave(self, event):
        if event.widget is self.root and self._resize_drag is None:
            self._set_edge_cursor(None)

    def _edge_press(self, event):
        zone = self._edge_zone(event)
        if zone:
            self._start_resize(zone, event)

    def _edge_motion(self, event):
        if self._resize_drag is not None:
            self._resize_to(event.x_root, event.y_root)

    def _edge_release(self, _event):
        if self._resize_drag is not None:
            self._end_resize()

    def _start_resize(self, zone, event):
        root = self.root
        self._resize_drag = (zone, event.x_root, event.y_root, root.winfo_x(), root.winfo_y(),
                             root.winfo_width(), root.winfo_height())

    def _resize_to(self, x_root, y_root):
        zone, x0, y0, left, top, w0, h0 = self._resize_drag
        dx, dy = x_root - x0, y_root - y0
        root = self.root
        width, height, x, y = w0, h0, left, top
        if "e" in zone or "w" in zone:
            width = w0 + dx if "e" in zone else w0 - dx
            width = max(self.min_w, min(width, root.winfo_vrootwidth()))
        if "s" in zone or "n" in zone:
            height = h0 + dy if "s" in zone else h0 - dy
            height = max(self.min_h, min(height, root.winfo_vrootheight()))
        geometry = f"{width}x{height}"
        if "w" in zone or "n" in zone:      # 從左邊或上邊拉：對面那條邊要留在原地，視窗位置跟著動
            if "w" in zone:
                x = left + w0 - width
            if "n" in zone:
                y = top + h0 - height
            geometry += f"+{x}+{y}"
        root.geometry(geometry)

    def _end_resize(self):
        self._resize_drag = None

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
            button.flash("check", COPY_DONE_FG, COPY_DONE_BG)

    def delete(self, text):
        index = self.store.items.index(text)
        self.store.remove(index)
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
        color = {"ok": OK, "warn": WARN, "undo": UNDO}.get(tone, MUTED)
        self.status.configure(text=text, fg=color, cursor="hand2" if undo else "")
        self._status_job = self.root.after(ms, self._clear_status)

    def _clear_status(self):
        self._status_job = None
        self._undo = None
        self.status.configure(text="", cursor="")

    def close(self):
        self._stop_drag()
        self.root.update()      # 讓剛複製的內容留在系統剪貼簿
        geometry = self._saved_geometry if self._minimized else self.root.geometry()
        self.store.set_window(geometry, self.pinned)
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
