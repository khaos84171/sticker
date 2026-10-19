"""pinclip 的測試。介面部分需要 tkinter 和顯示器；沒有的話會跳過。
Linux 沒有螢幕時：xvfb-run -a python -m pytest
"""
import json
import os
import shutil
import subprocess
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("tkinter")

import tkinter as tk

import pinclip
from pinclip import (Card, ClipStore, FlatButton, IconButton, PinClipApp, edge_at,
                     edge_scroll_step, fit_geometry, preview, stripe_color)


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


def test_move_reorders_and_persists(tmp_path):
    path = tmp_path / "p.json"
    store = ClipStore(path)
    for text in ("d", "c", "b", "a"):
        store.add(text)
    assert store.items == ["a", "b", "c", "d"]
    store.move(0, 2)
    assert store.items == ["b", "c", "a", "d"]
    store.move(3, 0)
    assert store.items == ["d", "b", "c", "a"]
    store.move(1, 1)                                    # 沒換位置就什麼都不做
    assert ClipStore(path).items == ["d", "b", "c", "a"]


def test_stripe_color_is_stable_per_text():
    assert stripe_color("同一段文字") == stripe_color("同一段文字")
    assert {stripe_color(f"項目 {i}") for i in range(40)} == set(pinclip.STRIPES)


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


@pytest.mark.parametrize("y, expected", [
    (150, 0),                     # 列表中間：不捲
    (32, 0), (200 - 32, 0),       # 剛好在邊緣區外面
    (31, -1), (169, 1),           # 剛進入邊緣區：只捲 1 像素
    (16, -2), (184, 2),           # 在邊緣區中間
    (0, -5), (200, 5),            # 在列表邊緣上
    (-32, -10), (-500, -10),      # 拖到列表外：最快，而且有上限
    (232, 10), (900, 10),
])
def test_edge_scroll_step(y, expected):
    assert edge_scroll_step(y, 200, 32, 10) == expected


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


def card_button(card, icon):
    return next(w for w in card.winfo_children() if isinstance(w, IconButton) and w.icon == icon)


def shown(app):
    """依畫面上由上到下的順序列出卡片（拖曳排序會改變順序，winfo_children 還是建立順序）。"""
    return [w for w in app.inner.pack_slaves() if isinstance(w, Card)]


def card_text(card):
    return card.winfo_children()[0].cget("text")


def event(**kwargs):
    return SimpleNamespace(**kwargs)


def test_starts_pinned_with_empty_hint(app):
    assert app.topmost_calls == [True]
    assert app.pin_button.icon == "pin"
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
    card_button(card, "copy").invoke()
    assert app.root.clipboard_get() == long_text             # 複製出來的是完整內容
    assert card_button(card, "check")                        # 按鈕暫時變成打勾


def test_clicking_the_text_also_copies(app):
    app.store.add("點文字也能複製")
    app.refresh()
    app.root.update()
    app.root.clipboard_clear()
    label = cards(app)[0].winfo_children()[0]
    label.event_generate("<ButtonPress-1>", x=5, y=5)
    label.event_generate("<ButtonRelease-1>", x=5, y=5)
    assert app.root.clipboard_get() == "點文字也能複製"


def test_never_reads_the_system_clipboard_on_its_own(app):
    """只保存你手動貼進輸入框的文字：程式本身從頭到尾都不會去讀系統剪貼簿。"""
    def forbidden(*args, **kwargs):
        raise AssertionError("不應該讀剪貼簿")

    app.root.clipboard_clear()
    app.root.clipboard_append("從別處複製的")
    app.root.clipboard_get = forbidden
    app.root.selection_get = forbidden
    app.root.update()
    assert app.store.items == []                             # 光是剪貼簿有東西，不會自己進來
    app.input.insert("1.0", "手動貼的")
    app.save_input()
    app.copy("手動貼的")
    app.delete("手動貼的")
    app.refresh()
    assert not hasattr(app, "paste_and_save")                # 沒有「貼上並儲存」


def test_save_row_has_only_the_save_button(app):
    actions = [w for w in app.body.winfo_children() if isinstance(w, tk.Frame)][1]
    buttons = [w.cget("text") for w in actions.winfo_children() if isinstance(w, FlatButton)]
    assert buttons == ["儲存"]


def test_delete_then_undo(app):
    for text in ("c", "b", "a"):
        app.store.add(text)
    app.refresh()
    card_button(cards(app)[1], "close").invoke()
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
    assert card_text(cards(app)[0]) == "最新的"


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
    copy_button = card_button(card, "copy")
    assert label.winfo_x() + label.winfo_reqwidth() <= copy_button.winfo_x()      # 文字不會被按鈕蓋住


def test_title_is_just_the_app_name(app):
    titles = [w.cget("text") for w in app.header.winfo_children() if isinstance(w, tk.Label)]
    assert titles == ["剪貼簿"]
    assert app.root.title() == "剪貼簿"
    texts = [w.cget("text") for w in app.header.winfo_children() if isinstance(w, FlatButton)]
    assert texts == []                                  # 標題列的按鈕都是圖標，沒有文字


# ---- 拖曳排序 ---------------------------------------------------------------

def three_cards(app):
    for text in ("c", "b", "a"):
        app.store.add(text)
    app.refresh()
    app.root.update()
    return cards(app)


def drag(app, card, to_y_root):
    """模擬按住卡片、拖到某個高度（螢幕座標）、放開。"""
    top = card.winfo_rooty() + 5
    app._card_press(event(x_root=100, y_root=top))
    app._card_motion(event(x_root=100, y_root=top + 10), card)
    app._card_motion(event(x_root=100, y_root=to_y_root), card)
    app._card_release(None)


def below(app, card):
    return card.winfo_rooty() + card.winfo_height()


def test_drag_first_card_to_the_bottom(app):
    a, b, c = three_cards(app)
    drag(app, a, below(app, c) + 5)
    app.root.update()
    assert app.store.items == ["b", "c", "a"]
    assert [card_text(x) for x in shown(app)] == ["b", "c", "a"]             # 畫面上也真的換了
    assert app._drag_card is None and app._autoscroll_job is None
    assert "已調整順序" in app.status.cget("text")
    assert ClipStore(app.store.path).items == ["b", "c", "a"]                # 存檔了


def test_drag_last_card_to_the_top(app):
    a, b, c = three_cards(app)
    drag(app, c, a.winfo_rooty() - 5)
    app.root.update()
    assert app.store.items == ["c", "a", "b"]


def test_drag_moves_cards_while_dragging_and_can_go_back(app):
    a, b, c = three_cards(app)
    top = a.winfo_rooty() + 5
    app._card_press(event(x_root=100, y_root=top))
    app._card_motion(event(x_root=100, y_root=top + 10), a)
    app._card_motion(event(x_root=100, y_root=below(app, c) + 5), a)
    assert [w.text for w in app.inner.pack_slaves()] == ["b", "c", "a"]       # 還沒放開就已經讓位
    app._card_motion(event(x_root=100, y_root=top), a)                        # 又拖回原位
    assert [w.text for w in app.inner.pack_slaves()] == ["a", "b", "c"]
    app._card_release(None)
    assert app.store.items == ["a", "b", "c"]
    assert "已調整順序" not in app.status.cget("text")                        # 沒換位置就不提示


def test_small_wobble_is_a_click_not_a_drag(app):
    app.store.add("只是點一下")
    app.refresh()
    app.root.update()
    card = cards(app)[0]
    app.root.clipboard_clear()
    app._card_press(event(x_root=100, y_root=100))
    app._card_motion(event(x_root=102, y_root=101), card)
    assert app._drag_card is None
    app._card_release(lambda: app.copy("只是點一下"))
    assert app.root.clipboard_get() == "只是點一下"


def test_dragging_does_not_copy(app):
    a, b, c = three_cards(app)
    app.root.clipboard_clear()
    app.root.clipboard_append("原本剪貼簿的內容")
    clicks = []
    top = a.winfo_rooty() + 5
    app._card_press(event(x_root=100, y_root=top))
    app._card_motion(event(x_root=100, y_root=top + 50), a)
    app._card_release(lambda: clicks.append(1))
    assert clicks == [] and app.root.clipboard_get() == "原本剪貼簿的內容"


def test_delete_after_reordering_removes_the_right_card(app):
    a, b, c = three_cards(app)
    drag(app, a, below(app, c) + 5)
    app.root.update()
    card_button(shown(app)[0], "close").invoke()                              # 現在畫面上第一張是 b
    assert app.store.items == ["c", "a"]
    assert [card_text(x) for x in shown(app)] == ["c", "a"]


def test_dragging_near_the_bottom_edge_scrolls_the_list(app):
    app.store.items = [f"項目 {i:02d}" for i in range(30)]
    app.refresh()
    app.root.update()
    first = app._cards[0]
    top = first.winfo_rooty() + 5
    app._card_press(event(x_root=100, y_root=top))
    app._card_motion(event(x_root=100, y_root=top + 12), first)
    edge = app.canvas.winfo_rooty() + app.canvas.winfo_height() - 5
    app.canvas.winfo_pointery = lambda: edge              # 沒有真的滑鼠，假裝游標停在列表下緣
    deadline = time.time() + 2
    while app.canvas.yview()[0] == 0 and time.time() < deadline:
        app.root.update()
        time.sleep(0.02)
    assert app.canvas.yview()[0] > 0                      # 列表自己往下捲了
    assert app._cards.index(first) > 0                    # 被拖的卡片跟著往下走
    app._card_release(None)
    assert app.store.items.index("項目 00") > 0
    assert app._autoscroll_job is None


def start_drag_at_the_bottom_edge(app):
    """抓住畫面上最後一張卡片、游標移到列表下緣附近（還沒放開），回傳 (卡片, 原本的位置)。"""
    app.store.items = [f"項目 {i:02d}" for i in range(30)]
    app.refresh()
    app.root.update()
    bottom = app.canvas.winfo_rooty() + app.canvas.winfo_height()
    card = [c for c in app._cards if c.winfo_rooty() + c.winfo_height() <= bottom][-1]
    index = app._cards.index(card)
    top = card.winfo_rooty() + 10
    app._card_press(event(x_root=100, y_root=top))
    near_edge = bottom - 12
    app.canvas.winfo_pointery = lambda: near_edge
    app._card_motion(event(x_root=100, y_root=near_edge), card)
    return card, index


def run_for(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.root.update()
        time.sleep(0.01)


def test_passing_through_the_edge_does_not_scroll(app):
    start_drag_at_the_bottom_edge(app)
    run_for(app, 0.25)                                    # 還沒停夠久
    assert app.canvas.canvasy(0) == 0
    app._card_release(None)


def test_edge_scrolling_is_slow_enough_not_to_rush_to_the_bottom(app):
    """回歸：游標只是移到列表下緣，整個列表曾經每秒衝 380 像素、卡片一路被推到最底。"""
    card, index = start_drag_at_the_bottom_edge(app)
    run_for(app, 1.5)
    scrolled = app.canvas.canvasy(0)
    assert 0 < scrolled < 150                             # 有在捲，但很慢
    assert app._cards.index(card) - index <= 3            # 卡片只跟著往下走幾格
    app._card_release(None)
    assert app.store.items.index(card.text) == app._cards.index(card)


def test_edge_scrolling_stops_when_the_pointer_leaves_the_edge(app):
    start_drag_at_the_bottom_edge(app)
    run_for(app, 0.9)
    app.canvas.winfo_pointery = lambda: app.canvas.winfo_rooty() + app.canvas.winfo_height() // 2
    run_for(app, 0.1)
    stopped_at = app.canvas.canvasy(0)
    run_for(app, 0.5)
    assert app.canvas.canvasy(0) == stopped_at
    app._card_release(None)


def test_mouse_wheel_scrolls_the_list_by_a_fixed_amount(app):
    app.store.items = [f"項目 {i:02d}" for i in range(30)]
    app.refresh()
    app.root.update()
    app._on_wheel(event(widget=app.canvas, num=0, delta=-120))
    app.root.update()
    assert app.canvas.canvasy(0) == app.px(40)
    app._on_wheel(event(widget=app.canvas, num=0, delta=120))
    app.root.update()
    assert app.canvas.canvasy(0) == 0


def test_drag_with_real_mouse_events_on_the_handle(app):
    a, b, c = three_cards(app)
    handle = next(w for w in a.winfo_children() if isinstance(w, tk.Canvas) and not isinstance(w, IconButton))
    handle.event_generate("<ButtonPress-1>", x=3, y=3, rootx=handle.winfo_rootx() + 3,
                          rooty=handle.winfo_rooty() + 3)
    handle.event_generate("<B1-Motion>", x=3, y=60, rootx=handle.winfo_rootx() + 3,
                          rooty=handle.winfo_rooty() + 60)
    handle.event_generate("<B1-Motion>", x=3, y=160, rootx=handle.winfo_rootx() + 3,
                          rooty=handle.winfo_rooty() + 160)
    handle.event_generate("<ButtonRelease-1>", x=3, y=160)
    app.root.update()
    assert app.store.items[0] != "a"                                          # 第一張被拖走了
    assert sorted(app.store.items) == ["a", "b", "c"]


# ---- 釘選、最小化、關閉 -----------------------------------------------------

def test_pin_button_toggles_topmost_and_label(app):
    app.pin_button.invoke()
    assert app.pinned is False and app.pin_button.icon == "pin_off"
    app.pin_button.invoke()
    assert app.pinned is True and app.pin_button.icon == "pin"
    assert app.topmost_calls == [True, False, True]


class WindowSpy:
    """記錄視窗被叫了哪些「換外框」「縮到工作列」的動作。

    測試環境沒有視窗管理員，真的 iconify 看不出效果，所以只記錄呼叫，
    並讓測試決定 state() 回報什麼（iconic = 還縮在工作列、normal = 已經還原）。
    """

    def __init__(self, app, monkeypatch):
        self.calls = []
        self.state = "normal"
        root = app.root
        real_override = root.overrideredirect

        def overrideredirect(*args):
            if args:
                self.calls.append(("overrideredirect", bool(args[0])))
            return real_override(*args)

        monkeypatch.setattr(root, "overrideredirect", overrideredirect)
        monkeypatch.setattr(root, "iconify", lambda: self.calls.append(("iconify",)))
        monkeypatch.setattr(root, "state", lambda *args: self.state)


def test_minimize_button_is_a_plain_minus_icon_and_nothing_is_hidden(app):
    assert app.minimize_button.icon == "minus"
    assert not hasattr(app, "toggle_collapse") and not hasattr(app, "collapsed")
    app.minimize_button.invoke()
    app.root.update()
    assert app.body.winfo_ismapped()                     # 不再把內容收起來、留一條標題列


def test_minimize_with_system_frame_just_iconifies(tmp_path, monkeypatch):
    native = build_app(tmp_path, False)
    try:
        spy = WindowSpy(native, monkeypatch)
        native.minimize_button.invoke()
        assert spy.calls == [("iconify",)]               # 系統外框的視窗本來就能最小化
        assert native._minimized is False
    finally:
        destroy(native)


def test_minimize_borderless_window_goes_to_the_taskbar_and_comes_back(custom_app, monkeypatch):
    app = custom_app
    app.root.geometry("333x444+120+60")
    app.root.update()
    spy = WindowSpy(app, monkeypatch)

    app.minimize_button.invoke()
    # 無外框的視窗不能直接最小化：先換回有外框，再縮到工作列
    assert spy.calls == [("overrideredirect", False), ("iconify",)]
    assert app._minimized is True

    spy.state = "iconic"
    app._on_map(event(widget=app.root))                  # 換外框時 Tk 也會送 Map，那不是還原
    assert spy.calls == [("overrideredirect", False), ("iconify",)] and app._minimized is True

    app.root.geometry("+140+110")                        # 有外框時位置會差一個標題列
    spy.state = "normal"
    app._on_map(event(widget=app.input))
    assert app._minimized is True                        # 子元件的 Map 不算
    app._on_map(event(widget=app.root))                  # 從工作列點開
    assert spy.calls[-1] == ("overrideredirect", True) and app._minimized is False
    app.root.update()
    assert (app.root.winfo_x(), app.root.winfo_y()) == (120, 60)     # 擺回原本的位置
    assert app.topmost_calls[-1] is True                              # 還是釘在最上層

    app._on_map(event(widget=app.root))                  # 之後的 Map（一般顯示）不會再動外框
    assert spy.calls[-1] == ("overrideredirect", True) and len(spy.calls) == 3


@pytest.mark.skipif(not shutil.which("openbox"), reason="需要 openbox（Linux 上模擬有視窗管理員的環境）")
def test_minimize_and_restore_with_a_real_window_manager(tmp_path):
    """用真的視窗管理員驗證：縮到工作列（iconic）、從工作列點開後換回無外框、位置還原。

    沒有視窗管理員時 iconify 看不出效果；有的話曾發現「換外框後立刻 iconify」不會生效，
    所以這個流程要在真的環境走一次。deiconify 代表從工作列點開。
    """
    if not os.environ.get("DISPLAY"):
        pytest.skip("沒有顯示器")
    wm = subprocess.Popen(["openbox"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    app = None
    try:
        time.sleep(1.0)
        app = build_app(tmp_path, True)
        root = app.root
        root.geometry("340x480+120+60")
        run_for(app, 0.5)

        def wait_for(condition, timeout=3.0):
            end = time.time() + timeout
            while time.time() < end and not condition():
                root.update()
                time.sleep(0.02)
            return condition()

        app.minimize_button.invoke()
        assert wait_for(lambda: root.state() == "iconic"), "沒有縮到工作列"
        assert app._minimized is True

        run_for(app, 0.5)                                   # 讓視窗管理員把縮下去的狀態處理完
        root.deiconify()                                    # 從工作列點開
        assert wait_for(lambda: root.state() == "normal" and not app._minimized), "沒有還原"
        run_for(app, 0.3)
        assert root.overrideredirect()                      # 又是無外框
        assert (root.winfo_x(), root.winfo_y(), root.winfo_width(), root.winfo_height()) == (120, 60, 340, 480)
    finally:
        if app is not None:
            destroy(app)
        wm.terminate()
        wm.wait(timeout=5)


def test_closing_from_the_taskbar_while_minimized_saves_the_normal_geometry(custom_app, monkeypatch, tmp_path):
    app = custom_app
    app.root.geometry("333x444+20+30")
    app.root.update()
    WindowSpy(app, monkeypatch)
    app.minimize_button.invoke()
    app.root.geometry("+500+500")                        # 縮到工作列期間的外框位置不要存進去
    app.close()
    assert ClipStore(tmp_path / "pinclip.json").window["geometry"] == "333x444+20+30"


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
        assert [card_text(c) for c in cards(again)] == ["重開之後還在"]
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
    app._start_resize("se", event(x_root=450, y_root=550))
    app._resize_to(500, 600)
    app.root.update()
    assert (app.root.winfo_width(), app.root.winfo_height()) == (450, 550)
    assert (app.root.winfo_x(), app.root.winfo_y()) == (50, 50)             # 右下角：左上角不動
    app._resize_to(-9999, -9999)
    app.root.update()
    assert (app.root.winfo_width(), app.root.winfo_height()) == (app.min_w, app.min_h)
    app._end_resize()


# ---- 拖曳邊框縮放（自繪標題列才有）-------------------------------------------

def shown_geometry(app):
    app.root.update()
    root = app.root
    return root.winfo_x(), root.winfo_y(), root.winfo_width(), root.winfo_height()


def press_edge(app, x, y):
    """在視窗邊框上 (x, y) 按下滑鼠（x, y 是視窗內座標），回傳換算成螢幕座標的函式。"""
    root = app.root
    start_x, start_y = root.winfo_rootx() + x, root.winfo_rooty() + y      # 按下時的螢幕座標
    root.event_generate("<ButtonPress-1>", x=x, y=y, rootx=start_x, rooty=start_y)

    def drag_to(dx, dy):
        """游標從按下的位置移動 (dx, dy)。視窗被拉動後座標會變，所以螢幕座標以按下時為準。"""
        root.event_generate("<B1-Motion>", x=x + dx, y=y + dy, rootx=start_x + dx,
                            rooty=start_y + dy)
        root.update()
    return drag_to


def release(app):
    app.root.event_generate("<ButtonRelease-1>", x=1, y=1)
    app.root.update()


@pytest.mark.parametrize("x, y, expected", [
    (200, 250, None),                                    # 內容區
    (2, 250, "w"), (397, 250, "e"), (200, 2, "n"), (200, 497, "s"),
    (2, 2, "nw"), (397, 2, "ne"), (2, 497, "sw"), (397, 497, "se"),
    (2, 10, "nw"), (10, 2, "nw"),                        # 邊上靠近角落的一段也算角落
    (397, 490, "se"), (390, 497, "se"),
    (2, 100, "w"), (100, 2, "n"),                        # 離角落夠遠就只是單邊
    (5, 250, None), (200, 5, None),                      # 剛好在邊框外（邊框厚度 5）
])
def test_edge_at(x, y, expected):
    assert edge_at(x, y, 400, 500, 5, 18) == expected


def test_border_shows_resize_cursor_and_interior_resets_it(custom_app):
    app = custom_app
    root = app.root
    root.event_generate("<Motion>", x=2, y=250)
    assert root.cget("cursor") in ("size_we", "sb_h_double_arrow")
    root.event_generate("<Motion>", x=2, y=2)
    assert root.cget("cursor") in ("size_nw_se", "top_left_corner")
    root.event_generate("<Motion>", x=200, y=250)
    assert root.cget("cursor") == ""
    app.header.event_generate("<Motion>", x=20, y=10)          # 在標題列（子元件）上也不留下縮放游標
    assert root.cget("cursor") == ""


def test_drag_left_edge_keeps_the_right_edge_in_place(custom_app):
    app = custom_app
    app.root.geometry("400x500+200+100")
    x, y, w, h = shown_geometry(app)
    drag_to = press_edge(app, 2, 250)
    drag_to(-60, 0)
    assert shown_geometry(app) == (x - 60, y, w + 60, h)       # 往左拉：變寬，右邊界不動
    drag_to(40, 0)
    assert shown_geometry(app) == (x + 40, y, w - 40, h)       # 往右推：變窄
    release(app)
    assert app._resize_drag is None


def test_drag_right_and_bottom_edges(custom_app):
    app = custom_app
    app.root.geometry("400x500+200+100")
    x, y, w, h = shown_geometry(app)
    press_edge(app, 398, 250)(50, 0)
    assert shown_geometry(app) == (x, y, w + 50, h)
    release(app)
    press_edge(app, 200, 498)(0, 30)
    assert shown_geometry(app)[2:] == (w + 50, h + 30)
    release(app)


def test_drag_top_edge_keeps_the_bottom_edge_in_place(custom_app):
    app = custom_app
    app.root.geometry("400x500+200+100")
    x, y, w, h = shown_geometry(app)
    press_edge(app, 200, 2)(0, -80)
    assert shown_geometry(app) == (x, y - 80, w, h + 80)


def test_drag_corners_resize_both_directions(custom_app):
    app = custom_app
    app.root.geometry("400x500+200+100")
    x, y, w, h = shown_geometry(app)
    press_edge(app, 2, 2)(-30, -20)                            # 左上角
    assert shown_geometry(app) == (x - 30, y - 20, w + 30, h + 20)
    release(app)
    x, y, w, h = shown_geometry(app)
    press_edge(app, w - 3, h - 3)(25, 15)                      # 右下角
    assert shown_geometry(app) == (x, y, w + 25, h + 15)
    release(app)


def test_resizing_from_the_left_stops_at_the_minimum_without_moving_the_right_edge(custom_app):
    app = custom_app
    app.root.geometry("400x500+200+100")
    x, y, w, h = shown_geometry(app)
    press_edge(app, 2, 250)(900, 0)                            # 一直往右推
    nx, ny, nw, nh = shown_geometry(app)
    assert nw == app.min_w and nx + nw == x + w                # 不能再窄，而且右邊界沒被推走
    release(app)


def test_pressing_inside_the_window_does_not_resize(custom_app):
    app = custom_app
    app.root.geometry("400x500+200+100")
    before = shown_geometry(app)
    label_card = None
    app.store.add("內容")
    app.refresh()
    app.root.update()
    card = cards(app)[0]
    card.event_generate("<ButtonPress-1>", x=3, y=3)           # 卡片上（不是視窗邊框）
    app.root.event_generate("<B1-Motion>", x=3, y=3, rootx=700, rooty=700)
    app.root.update()
    assert shown_geometry(app) == before and app._resize_drag is None


def test_native_frame_leaves_resizing_to_the_system(tmp_path):
    native = build_app(tmp_path, False)
    try:
        native.root.geometry("400x500+200+100")
        before = shown_geometry(native)
        native.root.event_generate("<ButtonPress-1>", x=1, y=250)
        native.root.event_generate("<B1-Motion>", x=1, y=250, rootx=100, rooty=250)
        native.root.update()
        assert shown_geometry(native) == before and native._border == 0
    finally:
        destroy(native)


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
    button = card_button(cards(app)[0], "copy")
    button.flash("check", "#ffffff", "#009900", ms=10)
    app.refresh()                                         # 列表重建，按鈕被丟掉
    time.sleep(0.05)
    app.root.update()
    assert not (tmp_path / "pinclip_error.log").exists()


@pytest.mark.parametrize("icon", ["minus", "close", "check", "copy", "pin", "pin_off"])
def test_every_icon_draws_something(app, icon):
    button = IconButton(app.root, icon, lambda: None, width=40, height=30, icon_size=16,
                        fg="#000000", bg="#ffffff")
    button.pack()
    app.root.update()
    assert len(button.find_all()) >= 2                    # 底色加上至少一個線條或形狀


def test_icon_button_hover_and_flash_restore_colors(app):
    button = IconButton(app.root, "copy", lambda: None, width=40, height=30, icon_size=16,
                        fg="#111111", bg="#eeeeee", hover_bg="#dddddd")
    button.pack()
    app.root.update()
    button.event_generate("<Enter>")
    assert button._current == ("#111111", "#dddddd")
    button.event_generate("<Leave>")
    assert button._current == ("#111111", "#eeeeee")
    button.flash("check", "#ffffff", "#009900", ms=10)
    assert button.icon == "check" and button._current == ("#ffffff", "#009900")
    time.sleep(0.05)
    app.root.update()
    assert button.icon == "copy" and button._current == ("#111111", "#eeeeee")


def test_callback_error_goes_to_log_file(app, tmp_path):
    try:
        raise ValueError("測試用錯誤")
    except ValueError as exc:
        app._on_callback_error(type(exc), exc, exc.__traceback__)
    assert "測試用錯誤" in (tmp_path / "pinclip_error.log").read_text(encoding="utf-8")
    assert "pinclip_error.log" in app.status.cget("text")
