"""pinclip 的測試。介面部分需要 tkinter 和顯示器；沒有的話會跳過。
Linux 沒有螢幕時：xvfb-run -a python -m pytest
"""
import json
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("tkinter")

import tkinter as tk

import pinclip
from pinclip import Card, ClipStore, FlatButton, PinClipApp, fit_geometry, preview


# ---- 純邏輯 ----------------------------------------------------------------

def test_add_puts_newest_first_and_persists(tmp_path):
    path = tmp_path / "d" / "pinclip.json"
    store = ClipStore(path)
    assert store.add("第一筆") and store.add("第二筆")
    assert store.items == ["第二筆", "第一筆"]
    assert ClipStore(path).items == ["第二筆", "第一筆"]


def test_blank_text_is_rejected(tmp_path):
    store = ClipStore(tmp_path / "p.json")
    assert store.add("") is False
    assert store.add("  \n\t ") is False
    assert store.items == []


def test_same_text_moves_to_front_instead_of_duplicating(tmp_path):
    store = ClipStore(tmp_path / "p.json")
    store.add("a")
    store.add("b")
    store.add("a")
    assert store.items == ["a", "b"]


def test_text_is_kept_exactly(tmp_path):
    path = tmp_path / "p.json"
    text = "  開頭空白\n第二行 \n\n日本語 ✓ \"引號\" \\反斜線"
    ClipStore(path).add(text)
    assert ClipStore(path).items == [text]


def test_remove_and_restore_at_same_position(tmp_path):
    store = ClipStore(tmp_path / "p.json")
    for text in ("c", "b", "a"):
        store.add(text)
    assert store.items == ["a", "b", "c"]
    removed = store.remove(1)
    assert removed == "b" and store.items == ["a", "c"]
    store.restore(1, removed)
    assert store.items == ["a", "b", "c"]


def test_missing_file_gives_empty_store(tmp_path):
    store = ClipStore(tmp_path / "nope.json")
    assert store.items == [] and store.window == {}


def test_corrupt_file_is_kept_as_bad_copy(tmp_path):
    path = tmp_path / "p.json"
    path.write_text("{壞掉的json", encoding="utf-8")
    store = ClipStore(path)
    assert store.items == []
    assert (tmp_path / "p.json.bad").read_text(encoding="utf-8") == "{壞掉的json"
    store.add("新的")                                   # 之後照常能存
    assert ClipStore(path).items == ["新的"]
    assert (tmp_path / "p.json.bad").exists()


def test_wrong_shapes_are_ignored(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"items": ["ok", 3, None, "  ", ["x"]], "window": "x"}),
                    encoding="utf-8")
    store = ClipStore(path)
    assert store.items == ["ok"] and store.window == {}
    path.write_text("[1, 2]", encoding="utf-8")
    assert ClipStore(path).items == []


def test_save_failure_is_reported_and_keeps_old_file(tmp_path, monkeypatch):
    path = tmp_path / "p.json"
    store = ClipStore(path)
    store.add("舊的")

    def boom(*args, **kwargs):
        raise PermissionError("被占用")

    monkeypatch.setattr(pinclip.os, "replace", boom)
    assert store.add("新的") is True                    # 記憶體裡有，畫面照常
    assert store.save_failed is True
    assert json.loads(path.read_text(encoding="utf-8"))["items"] == ["舊的"]


def test_data_path_override_and_platforms(monkeypatch, tmp_path):
    monkeypatch.setenv("PINCLIP_DATA", str(tmp_path / "x.json"))
    assert pinclip.default_data_path() == tmp_path / "x.json"
    monkeypatch.delenv("PINCLIP_DATA")
    monkeypatch.setattr(pinclip.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert pinclip.default_data_path() == tmp_path / "xdg" / "pinclip" / "pinclip.json"


def test_preview_truncates_lines_and_chars():
    assert preview("短短的") == "短短的"
    assert preview("1\n2\n3") == "1\n2\n3"
    assert preview("1\n2\n3\n4") == "1\n2\n3…"
    assert preview("字" * 500) == "字" * 140 + "…"
    assert preview("\n\n  縮排的開頭\n") == "縮排的開頭"


SCREEN = (0, 0, 1920, 1080)
DUAL = (-1920, 0, 3840, 1080)       # 副螢幕在左邊，虛擬桌面從 -1920 開始


@pytest.mark.parametrize("geometry, screen, expected", [
    ("400x300+100+50", SCREEN, "400x300+100+50"),
    ("400x300", SCREEN, "400x300"),
    ("400x300+5000+50", SCREEN, "400x300"),             # 螢幕拔掉了，位置看不到
    ("400x300+100+5000", SCREEN, "400x300"),
    ("400x300+-3000+50", SCREEN, "400x300"),
    ("400x300+-1200+50", SCREEN, "400x300"),
    ("400x300+-1200+50", DUAL, "400x300+-1200+50"),     # 有副螢幕時，左邊的位置是合法的
    ("9999x9999+0+0", SCREEN, "1920x1080+0+0"),
    ("10x10+0+0", SCREEN, "260x300+0+0"),
    ("亂寫的", SCREEN, "360x520"),
    (None, SCREEN, "360x520"),
])
def test_fit_geometry(geometry, screen, expected):
    assert fit_geometry(geometry, *screen) == expected


def test_custom_frame_choice(monkeypatch):
    monkeypatch.delenv("PINCLIP_FRAME", raising=False)
    monkeypatch.setattr(pinclip.sys, "platform", "win32")
    assert pinclip.want_custom_frame() is True
    monkeypatch.setattr(pinclip.sys, "platform", "linux")
    assert pinclip.want_custom_frame() is False         # 其他系統的無外框視窗常拿不到鍵盤焦點
    monkeypatch.setenv("PINCLIP_FRAME", "custom")
    assert pinclip.want_custom_frame() is True
    monkeypatch.setattr(pinclip.sys, "platform", "win32")
    monkeypatch.setenv("PINCLIP_FRAME", "native")
    assert pinclip.want_custom_frame() is False


# ---- 介面 ------------------------------------------------------------------

def build_app(tmp_path, custom_frame):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("沒有顯示器")
    topmost_calls = []
    real_attributes = root.attributes

    def attributes(*args):
        if len(args) == 2 and args[0] == "-topmost":
            topmost_calls.append(bool(args[1]))       # 沒有視窗管理員的測試環境讀不回 topmost
        return real_attributes(*args)

    root.attributes = attributes
    application = PinClipApp(root, ClipStore(tmp_path / "pinclip.json"), custom_frame=custom_frame)
    application.topmost_calls = topmost_calls
    root.deiconify()
    root.update()
    return application


def destroy(app):
    try:
        app.root.destroy()
    except tk.TclError:
        pass


@pytest.fixture(params=[False, True], ids=["native", "custom"])
def app(request, tmp_path):
    """系統外框和自繪標題列兩種都要測。"""
    application = build_app(tmp_path, request.param)
    yield application
    destroy(application)


@pytest.fixture
def custom_app(tmp_path):
    application = build_app(tmp_path, True)
    yield application
    destroy(application)


def cards(app):
    return [c for c in app.inner.winfo_children() if isinstance(c, Card)]


def card_button(card, text):
    return next(w for w in card.winfo_children() if isinstance(w, FlatButton) and w.cget("text") == text)


def event(**kwargs):
    return SimpleNamespace(**kwargs)


def test_starts_pinned_with_empty_hint(app):
    assert app.topmost_calls == [True]
    assert app.pin_button.cget("text") == "已釘選"
    assert cards(app) == []


def test_typed_text_is_saved_with_ctrl_enter_and_input_clears(app):
    app.input.insert("1.0", "手動貼進來的字")
    app.input.focus_force()
    app.root.update()
    app.input.event_generate("<Control-Return>")
    app.root.update()
    assert app.store.items == ["手動貼進來的字"]
    assert app.input.get("1.0", "end-1c") == ""          # 沒有多出換行、輸入框已清空
    assert len(cards(app)) == 1
    assert "已儲存 1 筆" in app.count.cget("text")


def test_empty_input_is_not_saved(app):
    app.input.insert("1.0", "   ")
    app.save_input()
    assert app.store.items == []
    assert "沒有內容" in app.status.cget("text")


def test_copy_button_puts_full_text_on_clipboard(app):
    long_text = "第一行\n第二行\n第三行\n第四行\n" + "很長" * 200
    app.store.add(long_text)
    app.refresh()
    card = cards(app)[0]
    assert "…" in card.winfo_children()[0].cget("text")       # 卡片只顯示摘要
    card_button(card, "複製").invoke()
    assert app.root.clipboard_get() == long_text             # 複製出來的是完整內容
    assert card_button(card, "已複製 ✓")


def test_clicking_the_text_also_copies(app):
    app.store.add("點文字也能複製")
    app.refresh()
    app.root.update()
    app.root.clipboard_clear()
    cards(app)[0].winfo_children()[0].event_generate("<Button-1>")
    assert app.root.clipboard_get() == "點文字也能複製"


def test_paste_and_save_reads_clipboard_only_when_asked(app):
    app.root.clipboard_clear()
    app.root.clipboard_append("從別處複製的")
    app.root.update()
    assert app.store.items == []                             # 光是剪貼簿有東西，不會自己進來
    app.paste_and_save()
    assert app.store.items == ["從別處複製的"]


def test_paste_and_save_with_empty_clipboard(app):
    app.root.clipboard_clear()
    app.paste_and_save()
    assert app.store.items == []
    assert "剪貼簿裡沒有文字" in app.status.cget("text")


def test_delete_then_undo(app):
    for text in ("c", "b", "a"):
        app.store.add(text)
    app.refresh()
    card_button(cards(app)[1], "✕").invoke()
    assert app.store.items == ["a", "c"]
    app.status.event_generate("<Button-1>")
    assert app.store.items == ["a", "b", "c"]
    assert len(cards(app)) == 3


def test_new_item_scrolls_list_to_top_and_shows_first(app):
    for i in range(30):
        app.store.add(f"項目 {i}")
    app.refresh()
    app.root.update()
    app.canvas.yview_moveto(1)
    app.input.insert("1.0", "最新的")
    app.save_input()
    app.root.update()
    assert app.canvas.yview()[0] == 0
    assert cards(app)[0].winfo_children()[0].cget("text") == "最新的"


def test_scrollbar_only_shows_when_list_overflows(app):
    app.root.update()
    assert not app.scroll.winfo_manager()
    for i in range(30):
        app.store.add(f"項目 {i}")
    app.refresh()
    app.root.update()
    assert app.scroll.winfo_manager() == "place"


def test_long_text_wraps_inside_the_card(app):
    app.store.add("字" * 300)
    app.refresh()
    app.root.update()
    card = cards(app)[0]
    label = card.winfo_children()[0]
    copy_button = card_button(card, "複製")
    assert label.winfo_x() + label.winfo_reqwidth() <= copy_button.winfo_x()      # 文字不會被按鈕蓋住


# ---- 釘選、縮小、關閉 -------------------------------------------------------

def test_pin_button_toggles_topmost_and_label(app):
    app.pin_button.invoke()
    assert app.pinned is False and app.pin_button.cget("text") == "未釘選"
    app.pin_button.invoke()
    assert app.pinned is True and app.pin_button.cget("text") == "已釘選"
    assert app.topmost_calls == [True, False, True]


def test_collapse_shrinks_to_title_bar_and_restores(app):
    before = app.root.winfo_height()
    app.collapse_button.invoke()
    app.root.update()
    assert app.collapsed and not app.body.winfo_ismapped()
    assert app.root.winfo_height() == app.header.winfo_reqheight() + 2 * app._border
    assert app.collapse_button.cget("text") == "□"
    app.collapse_button.invoke()
    app.root.update()
    assert not app.collapsed and app.body.winfo_ismapped()
    assert app.root.winfo_height() == before
    assert app.collapse_button.cget("text") == "—"


def test_double_click_title_bar_collapses(app):
    for _ in range(2):                  # Tk 不讓直接產生 Double 事件，連按兩次
        app.header.event_generate("<ButtonPress-1>", x=5, y=5)
        app.header.event_generate("<ButtonRelease-1>", x=5, y=5)
    assert app.collapsed


def test_closing_while_collapsed_remembers_the_full_height(app, tmp_path):
    app.root.geometry("333x444+20+30")
    app.root.update()
    app.collapse_button.invoke()
    app.root.update()
    app.close()
    assert ClipStore(tmp_path / "pinclip.json").window["geometry"].startswith("333x444")


def test_close_button_saves_state_and_closes_the_window(app, tmp_path):
    app.store.add("留著")
    app.pin_button.invoke()
    app.root.geometry("333x444+20+30")
    app.root.update()
    app.close_button.invoke()
    with pytest.raises(tk.TclError):
        app.root.winfo_exists()
    saved = ClipStore(tmp_path / "pinclip.json")
    assert saved.items == ["留著"]
    assert saved.window["pinned"] is False
    assert saved.window["geometry"].startswith("333x444")


def test_items_survive_restart(app, tmp_path):
    app.store.add("重開之後還在")
    app.close()
    again = build_app(tmp_path, app.custom_frame)
    try:
        assert [c.winfo_children()[0].cget("text") for c in cards(again)] == ["重開之後還在"]
    finally:
        destroy(again)


# ---- 自繪標題列才有的：無外框、拖曳移動、右下角調整大小 ----------------------

def test_custom_frame_is_borderless_and_native_is_not(tmp_path):
    custom, native = build_app(tmp_path, True), build_app(tmp_path, False)
    try:
        assert custom.root.overrideredirect() and not native.root.overrideredirect()
        assert hasattr(custom, "grip") and not hasattr(native, "grip")
    finally:
        destroy(custom)
        destroy(native)


def test_drag_title_bar_moves_window(custom_app):
    root = custom_app.root
    root.geometry("+100+100")
    root.update()
    custom_app._drag_start(event(x_root=150, y_root=110))
    custom_app._drag_move(event(x_root=250, y_root=210))
    root.update()
    assert (root.winfo_x(), root.winfo_y()) == (200, 200)


def test_resize_grip_resizes_and_respects_minimum(custom_app):
    app = custom_app
    app.root.geometry("400x500+50+50")
    app.root.update()
    app._resize_start(event(x_root=450, y_root=550))
    app._resize_move(event(x_root=500, y_root=600))
    app.root.update()
    assert (app.root.winfo_width(), app.root.winfo_height()) == (450, 550)
    app._resize_move(event(x_root=-9999, y_root=-9999))
    app.root.update()
    assert (app.root.winfo_width(), app.root.winfo_height()) == (app.min_w, app.min_h)
    app._resize_end(None)
    assert app._expanded_height == app.min_h


# ---- FlatButton --------------------------------------------------------------

def test_flat_button_fires_only_when_released_inside(app):
    hits = []
    button = FlatButton(app.root, "x", lambda: hits.append(1), fg="#000000", bg="#ffffff")
    button.pack()
    app.root.update()
    button.event_generate("<ButtonRelease-1>", x=2, y=2)
    assert hits == [1]
    button.event_generate("<ButtonRelease-1>", x=-50, y=2)       # 按住後拖到按鈕外面再放開
    assert hits == [1]


def test_flat_button_flash_restores_text_and_colors(app):
    button = FlatButton(app.root, "複製", lambda: None, fg="#111111", bg="#eeeeee",
                        hover_fg="#222222", hover_bg="#dddddd")
    button.flash("已複製 ✓", "#ffffff", "#009900", ms=10)
    assert button.cget("text") == "已複製 ✓" and button.cget("bg") == "#009900"
    time.sleep(0.05)
    app.root.update()
    assert button.cget("text") == "複製" and button.cget("bg") == "#eeeeee"


def test_flash_after_the_card_was_rebuilt_does_not_error(app, tmp_path):
    app.store.add("a")
    app.refresh()
    app.root.update()
    button = card_button(cards(app)[0], "複製")
    button.flash("已複製 ✓", "#ffffff", "#009900", ms=10)
    app.refresh()                                         # 列表重建，按鈕被丟掉
    time.sleep(0.05)
    app.root.update()
    assert not (tmp_path / "pinclip_error.log").exists()


def test_callback_error_goes_to_log_file(app, tmp_path):
    try:
        raise ValueError("測試用錯誤")
    except ValueError as exc:
        app._on_callback_error(type(exc), exc, exc.__traceback__)
    assert "測試用錯誤" in (tmp_path / "pinclip_error.log").read_text(encoding="utf-8")
    assert "pinclip_error.log" in app.status.cget("text")
