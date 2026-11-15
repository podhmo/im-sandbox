#!/usr/bin/env python3
# GUI e2e 用の観測用ミニエディタ (GTK3 TextView)。
#
# - バッファの内容を変更のたびに --output のファイルへ書き出す
# - 受け取ったキーイベントを --keylog のファイルへ記録する
#   (immodule に消費されたかどうかも分かるよう、イベントと確定文字列を記録)
# - --inject で指定したキー列を自分自身へ Gtk.test_widget_send_key で送る
#   (wayland では外部からのキー注入手段が無いため、アプリ内合成で代用する)
# - --quit-after 秒後、または --steps-file に書かれた回数分のキーを送り終わると終了
#
# usage:
#   GTK_IM_MODULE=fcitx GDK_BACKEND=x11 python3 tools/gtk_im_probe.py \
#       --output /tmp/buf.txt --keylog /tmp/keys.txt [--inject "a i u Ctrl+g e Enter"]
#
# キー表記は tools/mozc_e2e_fcitx5.py と同じ "Ctrl Shift f" 形式。
# 文字そのものの打鍵は 'a' のように1文字で書く (type: プレフィックスは使わない)。

import argparse
import signal
import sys

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib  # noqa: E402

SYM = {
    "Space": "space", "Enter": "Return", "Backspace": "BackSpace",
    "Delete": "Delete", "ESC": "Escape", "Tab": "Tab",
    "Home": "Home", "Left": "Left", "Up": "Up", "Right": "Right",
    "Down": "Down", "PageUp": "Page_Up", "PageDown": "Page_Down",
    "End": "End", "Zenkaku_Hankaku": "Zenkaku_Hankaku",
    "Eisu": "Eisu", "Hiragana_Katakana": "Hiragana_Katakana",
}
MOD = {"Ctrl": Gdk.ModifierType.CONTROL_MASK,
       "Shift": Gdk.ModifierType.SHIFT_MASK,
       "Alt": Gdk.ModifierType.MOD1_MASK,
       "Super": Gdk.ModifierType.SUPER_MASK}


def parse_key(spec):
    """'Ctrl Shift f' -> (keyval名, modifier)"""
    parts = spec.split(" ")
    name = parts[-1]
    state = Gdk.ModifierType(0)
    for m in parts[:-1]:
        state |= MOD[m]
    keyname = SYM.get(name, name if len(name) == 1 else None)
    if keyname is None:
        raise ValueError(f"unknown key: {spec}")
    return keyname, state


class Probe(Gtk.Window):
    def __init__(self, output, keylog):
        super().__init__(title="gtk-im-probe")
        self.set_default_size(480, 240)
        self.view = Gtk.TextView()
        self.buf = self.view.get_buffer()
        self.add(self.view)
        self.output = output
        self.keylog = open(keylog, "w") if keylog else None
        self.buf.connect("changed", self._on_changed)
        # バッファの変更は immodule に消費されたキーでは起きないので、
        # 「キーが届いたか」をイベント側からも記録する。
        # fcitx の GTK immodule は key snooper で消費するため、IMに消費された
        # キーは widget の key-press-event にすら届かない。
        # つまり key: 行に残る = アプリへ転送されたキー、となる。
        self.view.connect("key-press-event", self._on_key)
        self.connect("destroy", Gtk.main_quit)
        self.show_all()

    def _on_changed(self, buf):
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        with open(self.output, "w") as f:
            f.write(text)
        if self.keylog:
            self.keylog.write(f"commit-buffer: {text!r}\n")
            self.keylog.flush()

    def _on_key(self, widget, ev):
        if self.keylog:
            state = ev.state
            mods = "+".join(
                n for n, f in [("ctrl", state & Gdk.ModifierType.CONTROL_MASK),
                               ("shift", state & Gdk.ModifierType.SHIFT_MASK),
                               ("alt", state & Gdk.ModifierType.MOD1_MASK),
                               ("super", state & Gdk.ModifierType.SUPER_MASK)]
                if f)
            name = Gdk.keyval_name(ev.keyval)
            self.keylog.write(f"key: {mods} {name} -> {ev.string!r}\n")
            self.keylog.flush()
        return False

    def _send_key(self, keyval, state):
        """GdkEventKey を構築して自分の view に届ける。

        Gtk.test_widget_send_key は wayland バックエンドではイベントが
        widget まで届かない (key-press-event が発火しない) ため、
        widget.event() で直接ディスパッチする。
        immodule のフィルタは TextView の key-press-event ハンドラ内で
        呼ばれるので、この経路でも IM 処理は検証できる。
        """
        for evtype in (Gdk.EventType.KEY_PRESS, Gdk.EventType.KEY_RELEASE):
            ev = Gdk.Event.new(evtype)
            ev.window = self.view.get_window(Gtk.TextWindowType.TEXT)
            ev.time = Gdk.CURRENT_TIME
            ev.keyval = keyval
            ev.state = state
            ev.hardware_keycode = 0
            ev.group = 0
            ev.is_modifier = False
            ev.send_event = True
            self.view.event(ev)

    def inject(self, specs, interval=60):
        """自分自身へキーを合成する (wayland 用)。"""
        queue = list(specs)

        def step():
            if not queue:
                Gtk.main_quit()
                return GLib.SOURCE_REMOVE
            spec = queue.pop(0)
            try:
                keyname, state = parse_key(spec)
            except ValueError as e:
                if self.keylog:
                    self.keylog.write(f"!! {e}\n")
                    self.keylog.flush()
                return True
            keyval = Gdk.keyval_from_name(keyname)
            if keyval == 0:
                if self.keylog:
                    self.keylog.write(f"!! no keyval: {spec}\n")
                    self.keylog.flush()
                return True
            self._send_key(keyval, state)
            return True

        GLib.timeout_add(interval, step)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    p.add_argument("--keylog")
    p.add_argument("--inject-file",
                   help="キー列を書いたファイル (1行1キー) を自分へ送って終了")
    p.add_argument("--quit-after", type=float, default=0,
                   help="この秒数後に終了 (外部注入モード用)")
    args = p.parse_args()

    probe = Probe(args.output, args.keylog)
    if args.quit_after:
        GLib.timeout_add(int(args.quit_after * 1000), Gtk.main_quit)
    if args.inject_file:
        with open(args.inject_file) as f:
            specs = [l.strip() for l in f if l.strip() and not l.startswith("#")]
        # ウィンドウができてim moduleがattachしてから送る
        GLib.timeout_add(1200, lambda: probe.inject(specs)
                         or GLib.SOURCE_REMOVE)
    Gtk.main()
    return 0


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    sys.exit(main())
