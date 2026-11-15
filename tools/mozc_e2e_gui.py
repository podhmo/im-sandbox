#!/usr/bin/env python3
# GUI 経路の E2E: 実際の GTK3 アプリ (tools/gtk_im_probe.py) にキーを送り、
# バッファの内容を検証する。D-Bus 版 (mozc_e2e_fcitx5.py) と同じケースを使う。
#
# usage:
#   python3 tools/mozc_e2e_gui.py x11      # X11 (XWayland) + xdotool 注入
#   python3 tools/mozc_e2e_gui.py xim      # X11 + XIM 経由
#   python3 tools/mozc_e2e_gui.py wayland  # Wayland + アプリ内注入
#   [--only <case名の一部>] [--keep]
#
# モード:
#   x11     : GDK_BACKEND=x11 GTK_IM_MODULE=fcitx。xdotool (XTEST) でキーを送る。
#             WSLg では「実キー→RDP→weston→XWayland」の経路のうち、
#             XTEST→XWayland→アプリ以降を検証する。
#   xim     : 同じだが GTK_IM_MODULE=xim XMODIFIERS=@im=fcitx で XIM 経由。
#   wayland : GDK_BACKEND=wayland GTK_IM_MODULE=fcitx。WSLg には仮想キーボード
#             プロトコルが無いため、probe が Gtk.test_widget_send_key で
#             自分自身にキーを合成する。「アプリ→immodule」以降を検証する。
#
# 各ケースは probe を起動し直して IC を初期化し、fcitx5 のトリガーキー
# (Ctrl+Space) で mozc を活性化してからキー列を送る。

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROBE = os.path.join(HERE, "gtk_im_probe.py")
sys.path.insert(0, HERE)
from mozc_e2e_fcitx5 import CASES, check_expected  # noqa: E402

TRIGGER_SPEC = "Ctrl Space"

XDOTOOL_KEYS = {
    "Space": "space", "Enter": "Return", "Backspace": "BackSpace",
    "Delete": "Delete", "ESC": "Escape", "Tab": "Tab",
    "Home": "Home", "Left": "Left", "Up": "Up", "Right": "Right",
    "Down": "Down", "PageUp": "Page_Up", "PageDown": "Page_Down",
    "End": "End", "Zenkaku_Hankaku": "Zenkaku_Hankaku",
    "Eisu": "Eisu", "Hiragana_Katakana": "Hiragana_Katakana",
}
XDOTOOL_MODS = {"Ctrl": "ctrl", "Shift": "shift", "Alt": "alt", "Super": "super"}


def expand_steps(steps):
    """'type:aiu' を 'a','i','u' に展開する。"""
    out = []
    for s in steps:
        if s.startswith("type:"):
            out.extend(s[5:])
        else:
            out.append(s)
    return out


def xdotool_key(spec):
    parts = spec.split(" ")
    name = XDOTOOL_KEYS.get(parts[-1], parts[-1])
    mods = [XDOTOOL_MODS[m] for m in parts[:-1]]
    combo = "+".join(mods + [name])
    subprocess.run(["xdotool", "key", "--delay", "35", combo],
                   check=True, stderr=subprocess.DEVNULL)


def wait_file(path, timeout=8.0, settle=0.4):
    """ファイルが作られて内容が settle 秒間変化しなくなるまで待つ。"""
    deadline = time.time() + timeout
    last = None
    last_change = time.time()
    while time.time() < deadline:
        cur = None
        if os.path.exists(path):
            with open(path) as f:
                cur = f.read()
        if cur != last:
            last = cur
            last_change = time.time()
        elif last is not None and time.time() - last_change > settle:
            return last
        time.sleep(0.1)
    return last


LEARN_FILES = ["cform.db", "segment.db", "boundary.db", ".history.db"]


def _kill_mozc():
    """mozc_server を止めて消えるまで待つ (killall は非同期。

    停止中の flush が学習ファイルを汚さないよう、kill してから
    ファイルを動かすまでの間に待機を挟む)。"""
    subprocess.run(["killall", "mozc_server"], stderr=subprocess.DEVNULL)
    for _ in range(50):
        if subprocess.run(["pgrep", "-x", "mozc_server"],
                          capture_output=True).returncode != 0:
            return
        time.sleep(0.1)


class Runner:
    """学習ファイルの退避と復元。

    NO_HISTORY の設定差し替えをしない GUI 実行では、テスト中の確定が
    学習として残る。特に cform.db (文字種) は C-q などの結果が後続の
    変換表示に漏れるため、実行中は学習ファイルを退避する。
    """

    def __init__(self, mode, keep=False):
        self.mode = mode
        self.keep = keep
        self.tmp = tempfile.mkdtemp(prefix="mozc-e2e-gui-")
        self.buf = os.path.join(self.tmp, "buf.txt")
        self.keylog = os.path.join(self.tmp, "keys.txt")
        self.mozc_dir = os.path.expanduser("~/.config/mozc")
        self.stash = os.path.join(self.tmp, "learning")
        os.makedirs(self.stash)
        os.makedirs(self.mozc_dir, exist_ok=True)
        # 前回残った probe (とその IC) がフォーカスを競合させるので掃除する。
        # pkill -f は自分のコマンドライン (mozc_e2e_gui.py) にはマッチしない。
        subprocess.run(["pkill", "-f", "gtk_im_probe.py"],
                       stderr=subprocess.DEVNULL)
        time.sleep(0.3)
        _kill_mozc()
        try:
            for f in LEARN_FILES:
                p = os.path.join(self.mozc_dir, f)
                if os.path.exists(p):
                    shutil.move(p, os.path.join(self.stash, f))
        except Exception:
            self.restore()
            raise

    def restore(self):
        _kill_mozc()
        # 実行中に生成された学習ファイルを消してから退避分を戻す
        for f in LEARN_FILES:
            p = os.path.join(self.mozc_dir, f)
            if os.path.exists(p):
                os.remove(p)
        for f in LEARN_FILES:
            src = os.path.join(self.stash, f)
            if os.path.exists(src):
                shutil.move(src, os.path.join(self.mozc_dir, f))

    def env(self):
        env = dict(os.environ)
        if self.mode == "wayland":
            env["GDK_BACKEND"] = "wayland"
            env["GTK_IM_MODULE"] = "fcitx"
        else:
            env["GDK_BACKEND"] = "x11"
            if self.mode == "xim":
                env["GTK_IM_MODULE"] = "xim"
                env["XMODIFIERS"] = "@im=fcitx"
            else:
                env["GTK_IM_MODULE"] = "fcitx"
        return env

    def launch(self, steps_file=None):
        args = [sys.executable, PROBE,
                "--output", self.buf, "--keylog", self.keylog]
        if steps_file:
            args += ["--inject-file", steps_file]
        else:
            args += ["--quit-after", "30"]
        return subprocess.Popen(args, env=self.env(),
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)

    def activate_window(self, proc, timeout=10):
        # --pid で自分の probe の窓だけに絞る (残骸の窓を掴まない)
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = subprocess.run(
                ["xdotool", "search", "--pid", str(proc.pid),
                 "--name", "gtk-im-probe"],
                capture_output=True, text=True)
            wids = r.stdout.split()
            if wids:
                subprocess.run(["xdotool", "windowactivate", "--sync",
                                wids[-1]], stderr=subprocess.DEVNULL)
                return wids[-1]
            time.sleep(0.2)
        proc.kill()
        raise RuntimeError("probe window not found")

    def current_im(self):
        r = subprocess.run(
            ["busctl", "--user", "call", "org.fcitx.Fcitx5", "/controller",
             "org.fcitx.Fcitx.Controller1", "CurrentInputMethod"],
            capture_output=True, text=True)
        return r.stdout.strip().strip('"')

    def ensure_mozc_x(self, proc):
        # IC のフォーカス確立を待つ (CurrentInputMethod が空でなくなるまで)。
        # 直前のケースの IC が残っていると別 IC の状態を見てしまうので
        # フォーカスが奪われないよう、試行ごとに窓を再アクティブ化する。
        deadline = time.time() + 5
        while not self.current_im().strip('"s '):
            if time.time() > deadline:
                raise RuntimeError("probe の IC がフォーカスされない")
            time.sleep(0.2)
        for _ in range(8):
            if "mozc" in self.current_im():
                return
            self.activate_window(proc)
            xdotool_key(TRIGGER_SPEC)
            time.sleep(0.4)
        raise RuntimeError(f"mozc に切り替わらない: {self.current_im()}")

    def run_case(self, case):
        if os.path.exists(self.buf):
            os.remove(self.buf)
        if os.path.exists(self.keylog):
            os.remove(self.keylog)

        steps = expand_steps(case["steps"])
        if self.mode == "wayland":
            # アプリ内注入: トリガーで mozc を活性化してからキー列を送る
            sf = os.path.join(self.tmp, "steps.txt")
            with open(sf, "w") as f:
                f.write("\n".join([TRIGGER_SPEC] + steps))
            proc = self.launch(steps_file=sf)
            proc.wait(timeout=30)
            got = wait_file(self.buf) or ""
        else:
            proc = self.launch()
            try:
                self.ensure_mozc_x(proc)
                for s in steps:
                    xdotool_key(s)
                    time.sleep(0.04)
                    if s == "Space":
                        time.sleep(0.15)
                got = wait_file(self.buf, timeout=4) or ""
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
        return got

    def commit_count(self):
        """バッファ書き込み回数 = 確定の回数 (two-commits 判定用)。"""
        log = self.keylog_text()
        return sum(1 for l in log.splitlines()
                   if l.startswith("commit-buffer:"))

    def forwarded(self, spec):
        """spec のキーがアプリに転送されたか (keylog の key: 行を見る)。"""
        parts = spec.split(" ")
        name = parts[-1]
        mods = [m.lower() for m in parts[:-1]]
        for l in self.keylog_text().splitlines():
            if not l.startswith("key:"):
                continue
            fields = l[len("key:"):].split("->")[0].strip().split()
            *raw_mods, got_name = fields
            got_mods = {m for rm in raw_mods for m in rm.split("+")}
            if got_name != name:
                continue
            if all(m in got_mods for m in mods):
                return True
        return False

    def keylog_text(self):
        if os.path.exists(self.keylog):
            with open(self.keylog) as f:
                return f.read()
        return ""


def main():
    args = sys.argv[1:]
    mode = "x11"
    only = None
    keep = False
    i = 0
    while i < len(args):
        if args[i] in ("x11", "xim", "wayland"):
            mode = args[i]
        elif args[i] == "--only":
            i += 1
            only = args[i]
        elif args[i] == "--keep":
            keep = True
        else:
            print(f"unknown arg: {args[i]}", file=sys.stderr)
            sys.exit(2)
        i += 1

    # SIGTERM でも finally (学習ファイルの復元) が走るように SystemExit に変換
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(1))
    runner = Runner(mode, keep)
    failed = ran = 0
    try:
        for c in CASES:
            if only and only not in c["name"]:
                continue
            got = runner.run_case(c)
            expected = c.get("expect_commit_gui", c["expect_commit"])
            if expected == "<two-commits>":
                # GUI では確定が分割されたことをバッファ書き込み回数で判定する
                ok = runner.commit_count() >= 2
            else:
                ok = check_expected(got, expected, [got])
            for spec in c.get("expect_forwards", []):
                # 転送されたキーは keylog の key: 行に残る
                if not runner.forwarded(spec):
                    ok = False
            ran += 1
            if mode in c.get("xfail_modes", []) and not ok:
                print(f"XFAIL {c['name']} (既知の経路差分)")
                continue
            failed += (not ok)
            print(f"{'PASS' if ok else 'FAIL'}  {c['name']}")
            if not ok:
                print(f"      note:     {c['note']}")
                print(f"      expected: {expected!r}")
                print(f"      got:      {got!r}")
                print(f"      keylog:   {runner.keylog_text()!r}")
    finally:
        runner.restore()
        if not keep:
            import shutil
            shutil.rmtree(runner.tmp, ignore_errors=True)
        else:
            print(f"tmp: {runner.tmp}")
    print(f"\n{ran - failed}/{ran} passed (mode: {mode})")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
