#!/usr/bin/env python3
# fcitx5 + Mozc の E2E: D-Bus フロントエンド (org.fcitx.Fcitx.InputMethod1) に仮想
# 入力コンテキストを作り、キーイベントを送って CommitString / ForwardKey / preedit
# を検証する。GUI・実際のキー入力・特権は不要。
#
# usage: python3 tools/mozc_e2e_fcitx5.py [--im mozc] [--only <case名の一部>]
#
# 前提:
#   - fcitx5 が起動していること (WSLg では `fcitx5 -d --disable=wayland`)
#   - 対象 IM (既定 mozc) が fcitx5 のグループに登録されていること
#   - 学習の影響を避けるため history_learning_level: NO_HISTORY の config1.db を
#     適用した状態で実行すること (mozc/e2e.sh 経由が推奨)
#
# 変換候補は学習で変わるため、期待値は「変換候補によらず決まる」形にしている
# (文節を伸縮したあと C-j/C-q でひらがな/カタカナ表示にして確定する、など)。
#
# 制限: このテストは「アプリ→fcitx5」以降の経路を検証する。実キーボード→WSLg
# (RDP)→weston→アプリ の経路は対象外 (tools/mozc_e2e_gui.py を参照)。

import sys
import time
import dbus
import dbus.mainloop.glib
from gi.repository import GLib

ctx = GLib.MainContext.default()
bus = None  # main() で初期化。import 時に接続しない (CASES を import 再利用するため)


def ensure_bus():
    global bus
    if bus is None:
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        bus = dbus.SessionBus()

# ---- 定数 ----
# capabilityflags.h
CAP_CLIENT_SIDE_CONTROL_STATE = 1 << 2
CAP_CLIENT_SIDE_INPUT_PANEL = 1 << 39

# XKB keysym
SYM = {
    "Space": 0x20, "Enter": 0xFF0D, "Backspace": 0xFF08, "Delete": 0xFFFF,
    "ESC": 0xFF1B, "Tab": 0xFF09,
    "Home": 0xFF50, "Left": 0xFF51, "Up": 0xFF52, "Right": 0xFF53,
    "Down": 0xFF54, "PageUp": 0xFF55, "PageDown": 0xFF56, "End": 0xFF57,
    "Zenkaku_Hankaku": 0xFF2A, "Eisu": 0xFF2F, "Hiragana_Katakana": 0xFF27,
}
MOD = {"Ctrl": 1 << 2, "Shift": 1 << 0, "Alt": 1 << 3, "Super": 1 << 6}


def parse_key(spec):
    """'Ctrl Shift f' -> (keysym, state)"""
    parts = spec.split(" ")
    name = parts[-1]
    state = 0
    for m in parts[:-1]:
        state |= MOD[m]
    sym = SYM.get(name, ord(name) if len(name) == 1 else None)
    if sym is None:
        raise ValueError(f"unknown key: {spec}")
    return sym, state


def pump(sec=0.05):
    deadline = time.time() + sec
    while time.time() < deadline:
        while ctx.pending():
            ctx.iteration(False)
        time.sleep(0.005)


class IC:
    """fcitx5 の仮想入力コンテキスト。"""

    def __init__(self, im_if):
        self.path, _ = im_if.CreateInputContext(
            [("program", "mozc-e2e"), ("display", ":0")])
        obj = bus.get_object("org.fcitx.Fcitx5", self.path)
        self.ic = dbus.Interface(obj, "org.fcitx.Fcitx.InputContext1")
        self.commits = []
        self.forwards = []
        self.preedit = ""
        self.candidates = []
        self.current_im = ""
        for sig, fn in [
            ("CommitString", lambda s: self.commits.append(str(s))),
            ("ForwardKey", lambda v, st, rel: self.forwards.append((int(v), int(st)))),
            ("UpdateFormattedPreedit", self._on_preedit),
            ("UpdateClientSideUI", self._on_ui),
            ("CurrentIM", lambda n, u, l: setattr(self, "current_im", str(u))),
        ]:
            bus.add_signal_receiver(fn, signal_name=sig,
                                    dbus_interface="org.fcitx.Fcitx.InputContext1",
                                    path=self.path)
        self.ic.SetCapability(dbus.UInt64(
            CAP_CLIENT_SIDE_INPUT_PANEL | CAP_CLIENT_SIDE_CONTROL_STATE))
        self.ic.FocusIn()
        pump()

    def _on_preedit(self, text, pos):
        self.preedit = "".join(str(t[0]) for t in text)

    def _on_ui(self, preedit, cursor, aux_up, aux_down, candidates, idx,
               hint, prev, next_):
        self.preedit = "".join(str(t[0]) for t in preedit)
        self.candidates = [str(c[0]) for c in candidates]

    def key(self, spec):
        sym, state = parse_key(spec)
        accepted = self.ic.ProcessKeyEvent(
            dbus.UInt32(sym), dbus.UInt32(0), dbus.UInt32(state),
            dbus.Boolean(False), dbus.UInt32(0))
        self.ic.ProcessKeyEvent(
            dbus.UInt32(sym), dbus.UInt32(0), dbus.UInt32(state),
            dbus.Boolean(True), dbus.UInt32(0))
        pump()
        return bool(accepted)

    def reset(self):
        self.ic.Reset()
        self.commits.clear()
        self.forwards.clear()
        self.preedit = ""
        self.candidates = []
        pump()

    def destroy(self):
        try:
            self.ic.DestroyIC()
        except dbus.DBusException:
            pass


def run_steps(ic, steps):
    accepts = []
    for s in steps:
        if s.startswith("type:"):
            for ch in s[5:]:
                accepts.append((ch, ic.key(ch)))
        else:
            a = ic.key(s)
            accepts.append((s, a))
            if s == "Space":
                pump(0.15)  # 変換を待つ
    return accepts


# ---- テストケース ----
# steps: "type:xxx" は文字列打鍵、それ以外は 1 打鍵 (Mozc 風キー表記)
# expect_commit: 期待する確定文字列 ("<halves-equal>" は前半==後半)
# expect_forwards: 消費されずアプリへ転送されることを期待するキー
reading = "kokodehakimonowonugu"  # ここではきものをぬぐ
expand = ["Ctrl o"] * 12          # C-o (SegmentWidthExpand) で 1 文節にする

CASES = [
    dict(name="composition: C-g でキャンセル",
         note="読み入力中の C-g (Cancel) で未確定文字列が消える",
         steps=["type:aiu", "Ctrl g", "type:e", "Enter"],
         expect_commit="え"),
    dict(name="composition: C-b / C-d / C-a / C-e / C-h",
         note="読みの中でカーソル移動・削除",
         steps=["type:aiueo", "Ctrl b", "Ctrl b", "Ctrl d",
                "Ctrl a", "Ctrl d", "Ctrl e", "Ctrl h", "Enter"],
         expect_commit="いう"),
    dict(name="composition: C-n で変換に進む (PredictAndConvert)",
         note="読み入力中の C-n で予測変換に入り、確定すると読み以外が確定する",
         steps=["type:kanji", "Ctrl n", "Enter"],
         expect_commit="<not-hiragana>"),
    dict(name="conversion: C-g で変換キャンセル",
         note="変換中の C-g (Cancel) で読みに戻る",
         steps=["type:" + reading, "Space", "Ctrl g", "Enter"],
         expect_commit="ここではきものをぬぐ"),
    dict(name="conversion: C-o で文節を伸ばす",
         note="C-o (SegmentWidthExpand) を繰り返して 1 文節にし C-j で全体がひらがな",
         steps=["type:" + reading, "Space"] + expand + ["Ctrl j", "Enter"],
         expect_commit="ここではきものをぬぐ"),
    dict(name="conversion: C-i で縮める + C-e / C-a で文節移動",
         note="1 文節にしてから C-i (SegmentWidthShrink) で末尾を分割、C-e → C-q、C-a → C-j",
         steps=(["type:" + reading, "Space"] + expand
                + ["Ctrl i", "Ctrl e", "Ctrl q", "Ctrl a", "Ctrl j", "Enter"]),
         expect_commit="ここではきものをぬグ"),
    dict(name="conversion: C-f / C-b で文節移動",
         note="末尾を分割後、C-f → C-q、C-b → C-j",
         steps=(["type:" + reading, "Space"] + expand
                + ["Ctrl i", "Ctrl f", "Ctrl q", "Ctrl b", "Ctrl j", "Enter"]),
         expect_commit="ここではきものをぬグ"),
    dict(name="conversion: Tab も文節を縮める",
         note="Tab (SegmentWidthShrink)。C-i との区別がついていることも検証",
         steps=(["type:" + reading, "Space"] + expand
                + ["Tab", "Ctrl e", "Ctrl q", "Ctrl a", "Ctrl j", "Enter"]),
         expect_commit="ここではきものをぬグ"),
    dict(name="conversion: C-S-m で先頭の文節だけ確定",
         note="C-S-m (CommitOnlyFirstSegment) で確定が2回に分かれる (残りの文節は Enter で確定)。"
              " X11 では ctrl+shift+m が keysym 'M' として届き fcitx5 の正規化で"
              " Shift が落ち Ctrl+m (=Commit) 扱いになるため区別できない",
         steps=["type:" + reading, "Space", "Ctrl Shift m", "Enter"],
         expect_commit="<two-commits>",
         xfail_modes=["x11", "xim"]),
    dict(name="conversion: Shift Enter も先頭の文節だけ確定",
         note="Shift Enter (CommitOnlyFirstSegment)。C-S-m と同じコマンド",
         steps=["type:" + reading, "Space", "Shift Enter", "Enter"],
         expect_commit="<two-commits>"),
    dict(name="conversion: C-n → C-p で元の候補に戻る",
         note="ConvertNext と ConvertPrev が対。押さなかった場合と結果が一致する",
         steps=["type:kanji", "Space", "Ctrl n", "Ctrl p", "Enter",
                "type:kanji", "Space", "Enter"],
         expect_commit="<halves-equal>"),
    dict(name="precomposition: C-p / C-a はアプリに渡る",
         note="IMEオン・未入力時の C-p / C-a は消費されず転送される (accepted=False + ForwardKey)",
         steps=["Ctrl p", "Ctrl a"],
         expect_commit="",
         expect_forwards=["Ctrl p", "Ctrl a"]),
    dict(name="directinput: 半角/全角キーで IME オン/オフ",
         note="Precomposition の Zenkaku_Hankaku (IMEOff) で DIRECT へ。DIRECT では打鍵が転送され、もう一度押すと IMEOn",
         steps=["Zenkaku_Hankaku", "type:a", "Zenkaku_Hankaku", "type:a", "Enter"],
         expect_commit="あ",
         expect_commit_gui="aあ",
         expect_forwards=["a"]),
]


def check_expected(got, expected, commits):
    if expected == "<halves-equal>":
        n = len(got) // 2
        return len(got) % 2 == 0 and n > 0 and got[:n] == got[n:]
    if expected == "<not-hiragana>":
        return got != "かんじ" and len(got) > 0
    if expected == "<two-commits>":
        # CommitOnlyFirstSegment で確定が分割される。候補の中身には依存しない
        return len(commits) >= 2 and all(c for c in commits)
    return got == expected


def main():
    args = sys.argv[1:]
    im_name = "mozc"
    only = None
    i = 0
    while i < len(args):
        if args[i] == "--im":
            i += 1
            im_name = args[i]
        elif args[i] == "--only":
            i += 1
            only = args[i]
        else:
            print(f"unknown arg: {args[i]}", file=sys.stderr)
            sys.exit(2)
        i += 1

    ensure_bus()
    try:
        im = bus.get_object("org.fcitx.Fcitx5",
                            "/org/freedesktop/portal/inputmethod")
        im_if = dbus.Interface(im, "org.fcitx.Fcitx.InputMethod1")
        ctrl = dbus.Interface(
            bus.get_object("org.fcitx.Fcitx5", "/controller"),
            "org.fcitx.Fcitx.Controller1")
    except dbus.DBusException as e:
        print(f"fcitx5 に接続できない: {e}\n"
              "fcitx5 -d --disable=wayland で起動しているか確認する",
              file=sys.stderr)
        sys.exit(1)

    ic = IC(im_if)
    pump(0.1)
    prev_im = str(ctrl.CurrentInputMethod())
    if ic.current_im != im_name:
        ctrl.SetCurrentIM(im_name)
        pump(0.1)
    print(f"input method: {ic.current_im} (expected: {im_name})")
    if ic.current_im != im_name:
        print("IM を切り替えられなかった。fcitx5 の profile に "
              f"{im_name} が登録されているか確認する", file=sys.stderr)
        sys.exit(1)

    failed = ran = 0
    for c in CASES:
        if only and only not in c["name"]:
            continue
        ic.reset()
        accepts = run_steps(ic, c["steps"])
        pump(0.1)
        got = "".join(ic.commits)

        ok = check_expected(got, c["expect_commit"], ic.commits)
        fwd_expect = c.get("expect_forwards", [])
        for spec in fwd_expect:
            # 「アプリに渡る」= ProcessKeyEvent が accepted=False を返すこと。
            # (ForwardKey シグナルは IM が新しいキーを押し込む別経路なので使わない)
            # 同名キーが複数回出る場合は少なくとも1回転送されていればよい
            if not any(s == spec and a is False for s, a in accepts):
                ok = False
        ran += 1
        failed += (not ok)
        print(f"{'PASS' if ok else 'FAIL'}  {c['name']}")
        if not ok:
            print(f"      note:     {c['note']}")
            print(f"      expected: {c['expect_commit']!r} forwards={fwd_expect}")
            print(f"      got:      commit={got!r} forwards={ic.forwards} "
                  f"preedit={ic.preedit!r}")
            acc = " ".join(f"{s}={a}" for s, a in accepts)
            print(f"      accepts:  {acc}")

    ic.destroy()
    print(f"\n{ran - failed}/{ran} passed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
