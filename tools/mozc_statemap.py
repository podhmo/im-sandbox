#!/usr/bin/env python3
"""Mozc のキーマップを「状態遷移」の観点で眺める HTML を生成する (JavaScript なし)。

mozc_overview.py の表は網羅的だが、どの操作でどの状態へ移るのかが読み取りにくい。
このスクリプトは次の 4 つを 1 枚の HTML にまとめる。

  1. 状態遷移図 (SVG)。矢印は「その状態へ移る操作」のまとまり
  2. 遷移の一覧。矢印ごとに、コマンド・割り当てキー・条件
  3. 状態ごとの詳細。他の状態へ移る操作と、その状態に留まる操作 (分類ごと)
  4. キーから引く表。あるキーを各状態で押したときに何が起きるか

どのコマンドがどの状態へ遷移させるかは Mozc のソースから機械的には取れないため、
src/session/session.cc (Session::SendKey*State と各コマンドの実装) を読んで
TRANSITIONS に手で書いている。Mozc を更新したら見直すこと。

usage: python3 -I tools/mozc_statemap.py [--mozc DIR] [--config PATH] [--keymap NAME] [-o OUT]
"""

from __future__ import annotations

import argparse
import html
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

_spec = importlib.util.spec_from_file_location("mozc_overview", HERE / "mozc_overview.py")
ov = importlib.util.module_from_spec(_spec)
sys.dont_write_bytecode = True
_spec.loader.exec_module(ov)

# ---------------------------------------------------------------- 状態の定義

MAIN_STATES = ["DirectInput", "Precomposition", "Composition", "Conversion"]
# サブ状態: 親状態のキーマップを上書きする (未定義のキーは親の定義が使われる)
SUB_STATES = {
    "Precomposition": "ZeroQuerySuggestion",
    "Composition": "Suggestion",
    "Conversion": "Prediction",
}
STATE_JA = {
    "DirectInput": "直接入力 (IME オフ)",
    "Precomposition": "入力文字なし",
    "ZeroQuerySuggestion": "確定直後の候補表示中",
    "Composition": "変換前入力中",
    "Suggestion": "サジェスト表示中",
    "Conversion": "変換中",
    "Prediction": "予測候補の選択中",
}
STATE_DESC = {
    "DirectInput": "IME がオフの状態。キーマップにあるキー以外はそのままアプリへ渡る。",
    "Precomposition": "IME はオンだが未確定の文字がない状態。キーマップに無いキーはアプリへ渡る"
                      " (矢印キーや Enter がアプリで効くのはこのため)。",
    "ZeroQuerySuggestion": "確定直後に次の語の候補 (ゼロクエリサジェスト) が出ている間。主にモバイル向けで、"
                           "macOS ではほぼ出ない。",
    "Composition": "ひらがなを入力していて、まだ変換していない状態。キーマップに無いキーは IME が握りつぶす。",
    "Suggestion": "入力中にサジェスト候補のウィンドウが出ている間。Composition の定義を一部上書きする。",
    "Conversion": "変換して文節・候補を選んでいる状態。キーマップに無いキーは IME が握りつぶす。",
    "Prediction": "予測変換 (PredictAndConvert) で入った候補選択。Conversion の定義を一部上書きする。",
}
STATE_COLOR = {  # (線/文字, 背景)  ライト / ダーク は CSS 変数で切り替える
    "DirectInput": "d", "Precomposition": "p", "Composition": "c", "Conversion": "v",
}

# ---------------------------------------------------------------- 遷移の定義
# state -> command -> (遷移先 or None(留まる), 補足)
# session.cc の該当関数:
#   IMEOn/IMEOff/EditCancelAndIMEOff, EditCancel(SetStateToPredompositionAndCancel),
#   ConvertCancel(-> COMPOSITION), Commit(Internal), CommitSegment, CommitFirstSuggestion,
#   Convert/ConvertWithoutHistory/ConvertToTransliteration/SwitchKanaType/ConvertToHalfWidth(-> CONVERSION),
#   DisplayAs*(Composition では表示だけ変える。Conversion では ConvertTo* と同じ),
#   PredictAndConvert(Conversion では ConvertNext), Delete/Backspace(空になったら -> PRECOMPOSITION),
#   InsertCharacter(Conversion では確定してから入力), InsertSpace*(DIRECT_INPUT で InsertCharacter),
#   CompositionMode*(EnsureIMEIsOn), RequestConvertReverse/RequestUndo(クライアント経由)
CM = ["CompositionModeHiragana", "CompositionModeFullKatakana", "CompositionModeHalfKatakana",
      "CompositionModeFullAlphanumeric", "CompositionModeHalfAlphanumeric"]
CONVERT_TO = ["ConvertToHiragana", "ConvertToFullKatakana", "ConvertToHalfKatakana",
              "ConvertToHalfWidth", "ConvertToFullAlphanumeric", "ConvertToHalfAlphanumeric",
              "SwitchKanaType"]
SPACES = ["InsertSpace", "InsertAlternateSpace", "InsertHalfSpace", "InsertFullSpace"]

TRANSITIONS: dict[str, dict[str, tuple[str | None, str]]] = {
    "DirectInput": {
        "IMEOn": ("Precomposition", ""),
        **{c: ("Precomposition", "IME をオンにしてから入力モードを切り替える") for c in CM},
        "Reconvert": ("Conversion", "アプリで選択中の文字列を変換し直す (アプリ側の対応が必要)"),
    },
    "Precomposition": {
        "InsertCharacter": ("Composition", ""),
        "IMEOff": ("DirectInput", ""),
        "CancelAndIMEOff": ("DirectInput", ""),
        "Reconvert": ("Conversion", "アプリで選択中の文字列を変換し直す"),
        "Undo": ("Conversion", "確定直後のみ。確定を取り消して確定前に戻る。取り消すものが無ければキーはアプリへ"),
        "PredictAndConvert": ("Conversion", "ゼロクエリ候補が出ているときのみ (Prediction)"),
        **{c: (None, "空白をそのまま確定する") for c in SPACES},
        "CommitFirstSuggestion": (None, "ゼロクエリ候補の先頭を確定する"),
        "Cancel": (None, ""),
        "IMEOn": (None, "何もしない"),
    },
    "Composition": {
        "Commit": ("Precomposition", ""),
        "CommitFirstSuggestion": ("Precomposition", "サジェスト候補の先頭を確定"),
        "Cancel": ("Precomposition", "入力中の文字を破棄"),
        "Delete": ("Precomposition", "消して空になったときだけ。それ以外は留まる"),
        "Backspace": ("Precomposition", "消して空になったときだけ。それ以外は留まる"),
        "Convert": ("Conversion", ""),
        "ConvertWithoutHistory": ("Conversion", ""),
        **{c: ("Conversion", "") for c in CONVERT_TO},
        "PredictAndConvert": ("Conversion", "Prediction (予測候補の選択) に入る"),
        "IMEOff": ("DirectInput", "入力中の文字は確定される"),
        "CancelAndIMEOff": ("DirectInput", "入力中の文字は破棄される"),
        **{c: (None, "入力中の文字列に空白を足す") for c in SPACES},
        "IMEOn": (None, "何もしない"),
    },
    "Conversion": {
        "Cancel": ("Composition", "変換前のひらがなに戻る"),
        "InsertCharacter": ("Composition", "変換中の文字を確定してから、新しく入力を始める"),
        "Commit": ("Precomposition", ""),
        "CommitOnlyFirstSegment": ("Precomposition", "文節が 1 つだけのとき。それ以外は先頭を確定して留まる"),
        **{c: ("Precomposition", "変換中の文字を確定して空白を入力") for c in SPACES},
        "IMEOff": ("DirectInput", "変換中の文字は確定される"),
        "CancelAndIMEOff": ("DirectInput", "変換中の文字は破棄される"),
        "PredictAndConvert": (None, "次候補を選択と同じ"),
        "Undo": (None, "直前の文節確定などを取り消す"),
        "IMEOn": (None, "何もしない"),
    },
}

# 図の矢印に載せる短い名前 (コマンドのまとまり)
GROUP = {
    "IMEOn": "IME オン", "IMEOff": "IME オフ", "CancelAndIMEOff": "取消して IME オフ",
    **{c: "入力モード切替" for c in CM}, "Reconvert": "再変換", "InsertCharacter": "文字入力",
    "Undo": "確定取り消し", "PredictAndConvert": "予測変換", "CommitFirstSuggestion": "候補を確定",
    "Commit": "確定", "Cancel": "キャンセル", "Delete": "削除 (空に)", "Backspace": "削除 (空に)",
    "Convert": "変換", "ConvertWithoutHistory": "変換", **{c: "文字種変換" for c in CONVERT_TO},
    "CommitOnlyFirstSegment": "先頭文節確定", **{c: "空白" for c in SPACES},
}

# 状態に留まる操作の分類
CATEGORY = [
    ("入力", ["InsertCharacter", *SPACES]),
    ("削除", ["Delete", "Backspace"]),
    ("カーソル", ["MoveCursorLeft", "MoveCursorRight", "MoveCursorToBeginning", "MoveCursorToEnd"]),
    ("文節", ["SegmentFocusLeft", "SegmentFocusRight", "SegmentFocusFirst", "SegmentFocusLast",
              "SegmentWidthExpand", "SegmentWidthShrink", "CommitOnlyFirstSegment"]),
    ("候補", ["ConvertNext", "ConvertPrev", "ConvertNextPage", "ConvertPrevPage", "PredictAndConvert",
              "CommitFirstSuggestion", "DeleteSelectedCandidate"]),
    ("文字種", [*CONVERT_TO, "DisplayAsHiragana", "DisplayAsFullKatakana", "DisplayAsHalfKatakana",
                "DisplayAsHalfWidth", "DisplayAsFullAlphanumeric", "DisplayAsHalfAlphanumeric",
                "ToggleAlphanumericMode"]),
    ("入力モード", [*CM, "CompositionModeSwitchKanaType", "IMEOn"]),
    ("取り消し", ["Cancel", "Undo", "Revert"]),
    ("ツール", ["LaunchConfigDialog", "LaunchDictionaryTool", "LaunchWordRegisterDialog", "ReportBug"]),
]
CAT_OF = {c: cat for cat, cs in CATEGORY for c in cs}
EXTRA_JA = {"InsertCharacter": "文字を入力", "ReportBug": "バグ報告"}
KEY_JA = {"TextInput": "文字キー"}


def e(s) -> str:
    return html.escape(str(s) if s is not None else "")


def key_sort(k: str):
    return (k.lower().replace("ctrl ", "~").replace("shift ", "~~"), k)


# ---------------------------------------------------------------- モデル

class Model:
    def __init__(self, commands, noop, keymap, cmd_ja):
        self.commands = commands  # state -> [command]
        self.noop = noop
        self.keymap = keymap  # (state, key) -> command
        self.cmd_ja = cmd_ja

    def ja(self, cmd: str) -> str:
        return EXTRA_JA.get(cmd) or self.cmd_ja.get(cmd) or cmd

    def keys(self, state: str, cmd: str) -> list[str]:
        return sorted((k for (s, k), c in self.keymap.items() if s == state and c == cmd), key=key_sort)

    def effective(self, state: str, key: str) -> str | None:
        """サブ状態なら親状態へのフォールバックを含めて引く."""
        c = self.keymap.get((state, key))
        if c is None:
            parent = next((p for p, s in SUB_STATES.items() if s == state), None)
            if parent:
                c = self.keymap.get((parent, key))
        return c

    def sub_keys(self, state: str, cmd: str) -> list[str]:
        """サブ状態でだけこのコマンドに割り当てられているキー."""
        sub = SUB_STATES.get(state)
        if not sub:
            return []
        return [k for k in self.keys(sub, cmd) if self.keymap.get((state, k)) != cmd]

    def shadowed(self, state: str, key: str) -> str | None:
        """親状態のキーがサブ状態で別のコマンドに上書きされていれば、そのコマンド."""
        sub = SUB_STATES.get(state)
        if not sub:
            return None
        c = self.keymap.get((sub, key))
        return c if c and c != self.keymap.get((state, key)) else None

    def dest(self, state: str, cmd: str) -> tuple[str | None, str]:
        return TRANSITIONS.get(state, {}).get(cmd, (None, ""))

    def edges(self) -> dict[tuple[str, str], list[str]]:
        out: dict[tuple[str, str], list[str]] = {}
        for st in MAIN_STATES:
            for cmd in self.commands.get(st, []):
                d, _ = self.dest(st, cmd)
                if d:
                    out.setdefault((st, d), []).append(cmd)
        order = {s: i for i, s in enumerate(MAIN_STATES)}
        return dict(sorted(out.items(), key=lambda kv: (order[kv[0][0]], order[kv[0][1]])))

    def active(self, st: str, cmd: str) -> bool:
        return cmd not in self.noop and bool(self.keys(st, cmd) or self.sub_keys(st, cmd))


# ---------------------------------------------------------------- SVG

def text_width(s: str, size: float = 12) -> float:
    return sum(size if ord(ch) > 0x2000 else size * 0.58 for ch in s)


def render_svg(m: Model, edge_ids: dict) -> str:
    NW, NH, STEP, X0 = 190, 96, 300, 60
    OFF = [14, 38, 62]  # 距離 1/2/3 の矢印の出入り位置 (ノード中心から)
    TIER_GAP, LH = 34, 22
    xs = {s: X0 + i * STEP for i, s in enumerate(MAIN_STATES)}
    cx = {s: xs[s] + NW / 2 for s in MAIN_STATES}
    idx = {s: i for i, s in enumerate(MAIN_STATES)}

    # 段 (tier) の割り当て: 短い矢印ほどノードの近く。同じ段で水平区間が重ならないようにする
    placed = {"up": [], "down": []}
    layout = []
    for (a, b), cmds in sorted(m.edges().items(), key=lambda kv: abs(idx[kv[0][0]] - idx[kv[0][1]])):
        side = "up" if idx[b] > idx[a] else "down"
        dist = abs(idx[b] - idx[a])
        sx = cx[a] + (OFF[dist - 1] if side == "up" else -OFF[dist - 1])
        dx = cx[b] - (OFF[dist - 1] if side == "up" else -OFF[dist - 1])
        lo, hi = sorted((sx, dx))
        tier = 0
        while any(t == tier and not (hi < l2 or lo > h2) for t, l2, h2 in placed[side]):
            tier += 1
        placed[side].append((tier, lo, hi))
        groups = []
        for c in cmds:
            g = GROUP.get(c, m.ja(c))
            if g not in groups and m.active(a, c):
                groups.append(g)
        alive = bool(groups)
        if not groups:
            groups = list(dict.fromkeys(GROUP.get(c, m.ja(c)) for c in cmds))
        label = "・".join(groups[:3]) + ("…" if len(groups) > 3 else "")
        layout.append(dict(a=a, b=b, side=side, tier=tier, sx=sx, dx=dx, label=label,
                           alive=alive, id=edge_ids[(a, b)]))

    up_tiers = max([t for t, *_ in placed["up"]] + [0]) + 1
    down_tiers = max([t for t, *_ in placed["down"]] + [0]) + 1
    top = 30 + up_tiers * TIER_GAP + 10
    W = X0 * 2 + STEP * (len(MAIN_STATES) - 1) + NW
    H = top + NH + 30 + down_tiers * TIER_GAP + 20

    out = [f"<svg viewBox='0 0 {W} {H}' width='{W}' class=diagram role=img "
           f"aria-label='Mozc の状態遷移図'>",
           "<defs>" + "".join(
               f"<marker id='ar-{c}' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='7' markerHeight='7'"
               f" orient='auto-start-reverse'><path d='M0,0 L10,5 L0,10 z' class='fill-{c}'/></marker>"
               for c in [*STATE_COLOR.values(), "mute"]) + "</defs>"]

    paths, labels = [], []
    for ed in layout:
        if ed["side"] == "up":
            y0 = top
            y = top - 22 - ed["tier"] * TIER_GAP
        else:
            y0 = top + NH
            y = top + NH + 22 + ed["tier"] * TIER_GAP
        r = 8
        sgn = 1 if ed["dx"] > ed["sx"] else -1
        vy = -1 if ed["side"] == "up" else 1
        d = (f"M{ed['sx']},{y0} L{ed['sx']},{y - vy * r} "
             f"Q{ed['sx']},{y} {ed['sx'] + sgn * r},{y} "
             f"L{ed['dx'] - sgn * r},{y} Q{ed['dx']},{y} {ed['dx']},{y - vy * r} "
             f"L{ed['dx']},{y0}")
        col = STATE_COLOR[ed["b"]] if ed["alive"] else "mute"
        dash = "" if ed["alive"] else " stroke-dasharray='5 4'"
        paths.append(f"<a href='#edge-{ed['id']}'><path d='{d}' class='edge stroke-{col}'{dash}"
                     f" marker-end='url(#ar-{col})'/></a>")
        txt = f"{ed['id']} {ed['label']}"
        w = text_width(txt) + 14
        mx = (ed["sx"] + ed["dx"]) / 2
        labels.append(
            f"<a href='#edge-{ed['id']}'><g class='elabel{'' if ed['alive'] else ' dead'}'>"
            f"<rect x='{mx - w / 2:.1f}' y='{y - LH / 2}' width='{w:.1f}' height='{LH}' rx='4'"
            f" class='stroke-{col}'/>"
            f"<text x='{mx:.1f}' y='{y + 4}' text-anchor='middle'><tspan class='eid fill-{col}'>{e(ed['id'])}"
            f"</tspan> {e(ed['label'])}</text></g></a>")
    out += paths + labels

    for s in MAIN_STATES:
        c = STATE_COLOR[s]
        x = xs[s]
        out.append(f"<a href='#st-{s}'><g class='node'>"
                   f"<rect x='{x}' y='{top}' width='{NW}' height='{NH}' rx='10' class='stroke-{c} bg-{c}'/>"
                   f"<text x='{x + NW / 2}' y='{top + 24}' text-anchor='middle' class='nname fill-{c}'>{s}</text>"
                   f"<text x='{x + NW / 2}' y='{top + 42}' text-anchor='middle' class='nja'>{e(STATE_JA[s])}</text>")
        sub = SUB_STATES.get(s)
        if sub:
            out.append(f"<rect x='{x + 14}' y='{top + 54}' width='{NW - 28}' height='30' rx='6' class='sub stroke-{c}'/>"
                       f"<text x='{x + NW / 2}' y='{top + 73}' text-anchor='middle' class='nsub'>"
                       f"{sub}</text>")
        out.append("</g></a>")
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------- HTML

CSS = """
:root { --fg:#1d1d1f; --mute:#8e8e93; --bg:#fff; --line:#e5e5ea; --card:#f7f7f9; --acc:#0a66c2;
  --d:#6e6e73; --d-bg:#f2f2f4; --p:#1f6fd1; --p-bg:#eaf2fd; --c:#1f8a4c; --c-bg:#e8f6ee; --v:#c25e00; --v-bg:#fdf0e3; }
@media (prefers-color-scheme: dark) { :root { --fg:#f2f2f7; --mute:#8e8e93; --bg:#1c1c1e; --line:#38383a; --card:#26262a; --acc:#64a8ff;
  --d:#aeaeb2; --d-bg:#2c2c2e; --p:#6aa8ff; --p-bg:#1b2a40; --c:#5ccf8a; --c-bg:#173324; --v:#ffa257; --v-bg:#3d2915; } }
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { font: 14px/1.55 -apple-system, "Hiragino Sans", sans-serif; color: var(--fg); background: var(--bg); margin: 0; }
header { padding: 14px 24px 10px; border-bottom: 1px solid var(--line); position: sticky; top: 0; background: var(--bg); z-index: 3; }
h1 { font-size: 18px; margin: 0 0 4px; }
nav a { margin-right: 14px; color: var(--acc); text-decoration: none; font-size: 13px; }
main { padding: 0 24px 60px; max-width: 1400px; }
section { margin-top: 30px; scroll-margin-top: 80px; }
h2 { font-size: 17px; border-bottom: 2px solid var(--line); padding-bottom: 4px; }
h3 { font-size: 14px; margin: 18px 0 6px; }
p.note, .mute { color: var(--mute); font-size: 12px; }
code { font: 12px ui-monospace, Menlo, monospace; }
kbd { font: 11.5px ui-monospace, Menlo, monospace; border: 1px solid var(--line); border-bottom-width: 2px; border-radius: 4px;
  padding: 0 5px; margin: 1px 2px 1px 0; display: inline-block; background: var(--card); white-space: nowrap; }
kbd.sub { border-style: dashed; }
kbd.sub::after { content: attr(data-s); font-size: 9px; color: var(--mute); margin-left: 3px; }
table { border-collapse: collapse; width: 100%; }
th, td { border-bottom: 1px solid var(--line); padding: 5px 8px; text-align: left; vertical-align: top; }
th { font-weight: 600; font-size: 12px; color: var(--mute); }
.tag { display: inline-block; font-size: 10.5px; padding: 0 6px; border-radius: 8px; border: 1px solid var(--line); color: var(--mute); }
.st { display: inline-block; font-size: 12px; font-weight: 600; padding: 1px 8px; border-radius: 10px; text-decoration: none; white-space: nowrap; }
.st-d { color: var(--d); background: var(--d-bg); } .st-p { color: var(--p); background: var(--p-bg); }
.st-c { color: var(--c); background: var(--c-bg); } .st-v { color: var(--v); background: var(--v-bg); }
.dead, tr.dead td { opacity: .5; }
/* 図 */
.diagram-wrap { overflow-x: auto; background: var(--card); border-radius: 10px; padding: 8px; }
svg.diagram { display: block; max-width: none; font-family: -apple-system, "Hiragino Sans", sans-serif; }
svg .edge { fill: none; stroke-width: 1.8; }
svg a:hover .edge { stroke-width: 3; }
svg .elabel rect { fill: var(--bg); stroke-width: 1; }
svg .elabel text { font-size: 12px; fill: var(--fg); }
svg .elabel .eid { font-weight: 700; }
svg a:hover .elabel rect { stroke-width: 2.5; }
svg .node rect { stroke-width: 2; }
svg .node .sub { fill: var(--bg); stroke-dasharray: 4 3; stroke-width: 1; }
svg .nname { font-size: 15px; font-weight: 700; }
svg .nja { font-size: 12px; fill: var(--fg); }
svg .nsub { font-size: 11.5px; fill: var(--mute); }
svg a:hover .node rect:first-child { stroke-width: 3.5; }
.stroke-d { stroke: var(--d); } .stroke-p { stroke: var(--p); } .stroke-c { stroke: var(--c); } .stroke-v { stroke: var(--v); } .stroke-mute { stroke: var(--mute); }
.fill-d { fill: var(--d); } .fill-p { fill: var(--p); } .fill-c { fill: var(--c); } .fill-v { fill: var(--v); } .fill-mute { fill: var(--mute); }
.bg-d { fill: var(--d-bg); } .bg-p { fill: var(--p-bg); } .bg-c { fill: var(--c-bg); } .bg-v { fill: var(--v-bg); }
/* :target で飛んできた場所を強調 (JS なし) */
:target { animation: flash 1.6s ease-out; }
tr:target td { background: var(--card); }
@keyframes flash { from { outline: 3px solid var(--acc); outline-offset: 2px; } to { outline: 3px solid transparent; } }
/* 状態カード */
.state { border-left: 5px solid var(--line); padding-left: 16px; }
.state.s-d { border-color: var(--d); } .state.s-p { border-color: var(--p); } .state.s-c { border-color: var(--c); } .state.s-v { border-color: var(--v); }
.state h2 { border: none; }
.cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 0 28px; }
.cat td:first-child { white-space: nowrap; color: var(--mute); font-size: 12px; width: 6em; }
td.ops div { margin: 1px 0; }
.nw { white-space: nowrap; }
a.edgeid { color: var(--acc); text-decoration: none; }
.edgeid { font-weight: 700; font-family: ui-monospace, Menlo, monospace; }
/* キー表 */
table.keys td { font-size: 12px; }
table.keys td.k { white-space: nowrap; }
table.keys td.cell-d { background: var(--d-bg); } table.keys td.cell-p { background: var(--p-bg); }
table.keys td.cell-c { background: var(--c-bg); } table.keys td.cell-v { background: var(--v-bg); }
table.keys th { position: sticky; top: 62px; background: var(--bg); z-index: 1; }
table.keys .inh { color: var(--mute); }
.legend span { margin-right: 10px; }
"""


def st_badge(s: str, text: str | None = None) -> str:
    parent = next((p for p, sub in SUB_STATES.items() if sub == s), s)
    return (f"<a class='st st-{STATE_COLOR[parent]}' href='#st-{parent}'>"
            f"{e(text or s)}</a>")


def kbds(m: Model, st: str, cmd: str) -> str:
    out = []
    for k in m.keys(st, cmd):
        over = m.shadowed(st, k)
        title = f" title='{e(SUB_STATES[st])} では {e(m.ja(over))}'" if over else ""
        out.append(f"<kbd{title}>{e(KEY_JA.get(k, k))}</kbd>")
    sub = SUB_STATES.get(st)
    for k in m.sub_keys(st, cmd):
        out.append(f"<kbd class=sub data-s='{e(sub)}' title='{e(sub)} のときだけ'>{e(k)}</kbd>")
    return "".join(out) or "<span class=mute>(未割り当て)</span>"


def render(ctx: dict) -> str:
    m: Model = ctx["model"]
    edges = m.edges()
    edge_ids = {k: chr(ord("A") + i) for i, k in enumerate(edges)}
    w = (out := []).append

    w("<!doctype html><html lang=ja><meta charset=utf-8><meta name=viewport content='width=device-width'>")
    w("<title>Mozc 状態遷移とキー</title><style>" + CSS + "</style>")
    w("<header><h1>Mozc 状態遷移とキー</h1><nav><a href='#diagram'>状態遷移図</a><a href='#edges'>遷移一覧</a>"
      + "".join(f"<a href='#st-{s}'>{s}</a>" for s in MAIN_STATES)
      + "<a href='#keys'>キーから引く</a></nav></header><main>")
    w(f"<p class=note>キーマップ: <b>{e(ctx['keymap_name'])}</b> / 生成元: <code>{e(ctx['mozc'])}</code> "
      f"({e(ctx['rev'])}) / 設定: <code>{e(ctx['db'] or '(なし)')}</code></p>")

    # --- 図
    w("<section id=diagram><h2>状態遷移図</h2>")
    w("<p class=note>四角が状態、矢印が「その操作をすると移る先」。矢印の色は行き先の状態の色。"
      "点線の矢印は、現在のキーマップでキーが割り当てられていない遷移。"
      "破線の内枠はサブ状態 (候補ウィンドウが出ている間だけ、親状態のキー定義を一部上書きする)。"
      "矢印や状態をクリックすると説明へ移動する。どの状態でも、キーマップに無い操作は状態を変えない。</p>")
    w("<div class=diagram-wrap>" + render_svg(m, edge_ids) + "</div></section>")

    # --- 遷移一覧
    w("<section id=edges><h2>遷移一覧</h2>")
    w("<table><tr><th></th><th>遷移</th><th>操作</th><th>キー</th><th>補足</th></tr>")
    for (a, b), cmds in edges.items():
        eid = edge_ids[(a, b)]
        live = [c for c in cmds if m.active(a, c)]
        dead = [c for c in cmds if not m.active(a, c)]
        rows = []
        for c in live:
            _, note = m.dest(a, c)
            rows.append(f"<td>{e(m.ja(c))} <code class=mute>{e(c)}</code></td>"
                        f"<td>{kbds(m, a, c)}</td><td class=mute>{e(note)}</td>")
        if dead:
            rows.append("<td colspan=3 class=mute>キー未割り当て: " + "、".join(
                e(m.ja(c)) + (" (macOS では無効)" if c in m.noop else "") for c in dead) + "</td>")
        for i, r in enumerate(rows):
            head = (f"<td rowspan={len(rows)} class=edgeid>{eid}</td>"
                    f"<td rowspan={len(rows)} class=nw>{st_badge(a)} → {st_badge(b)}</td>") if i == 0 else ""
            rid = f" id='edge-{eid}'" if i == 0 else ""
            cls = " class=dead" if not live else ""
            w(f"<tr{rid}{cls}>{head}{r}</tr>")
    w("</table></section>")

    # --- 状態ごと
    for st in MAIN_STATES:
        c = STATE_COLOR[st]
        sub = SUB_STATES.get(st)
        cmds = m.commands.get(st, [])
        incoming = [(k, v) for k, v in edges.items() if k[1] == st]
        outgoing = [(k, v) for k, v in edges.items() if k[0] == st]
        w(f"<section id=st-{st} class='state s-{c}'><h2>{st_badge(st)} {e(STATE_JA[st])}</h2>")
        w(f"<p>{e(STATE_DESC[st])}</p>")
        if sub:
            w(f"<p class=note>サブ状態 <b>{e(sub)}</b> ({e(STATE_JA[sub])}): {e(STATE_DESC[sub])}"
              f" 破線のキー <kbd class=sub data-s='{e(sub)}'>…</kbd> はサブ状態のときだけ効く。</p>")
        w("<p class=note>入ってくる遷移: " + " ".join(
            f"<a href='#edge-{edge_ids[k]}' class=edgeid>{edge_ids[k]}</a> {st_badge(k[0])}"
            for k, _ in incoming) + "</p>")
        w("<div class=cols><div>")
        w("<h3>他の状態へ移る操作</h3><table><tr><th>行き先</th><th>操作</th><th>キー</th></tr>")
        for (a, b), ecmds in outgoing:
            rows = []
            for cmd in ecmds:
                if not m.active(st, cmd):
                    continue
                _, note = m.dest(st, cmd)
                rows.append(f"<td>{e(m.ja(cmd))}"
                            + (f"<br><span class=mute>{e(note)}</span>" if note else "")
                            + f"</td><td>{kbds(m, st, cmd)}</td>")
            dead = [c for c in ecmds if not m.active(st, c)]
            if dead:
                rows.append("<td colspan=2 class=mute>キー未割り当て: "
                            + "、".join(e(m.ja(c)) for c in dead) + "</td>")
            for i, r in enumerate(rows):
                head = (f"<td rowspan={len(rows)} class=nw><a class=edgeid href='#edge-{edge_ids[(a, b)]}'>"
                        f"{edge_ids[(a, b)]}</a> → {st_badge(b)}</td>") if i == 0 else ""
                w(f"<tr>{head}{r}</tr>")
        w("</table></div><div>")
        w("<h3>この状態のままの操作</h3><table class=cat><tr><th>分類</th><th>操作とキー</th></tr>")
        stay = [cmd for cmd in cmds if not m.dest(st, cmd)[0]]
        cats: dict[str, list[str]] = {}
        for cmd in stay:
            cats.setdefault(CAT_OF.get(cmd, "その他"), []).append(cmd)
        unassigned = []
        if not stay:
            w("<tr><td colspan=2 class=mute>なし</td></tr>")
        for cat, _ in [*CATEGORY, ("その他", [])]:
            rows = []
            for cmd in cats.get(cat, []):
                if cmd in m.noop or not (m.keys(st, cmd) or m.sub_keys(st, cmd)):
                    unassigned.append(cmd)
                    continue
                _, note = m.dest(st, cmd)
                rows.append(f"<div>{e(m.ja(cmd))}{' <span class=mute>(' + e(note) + ')</span>' if note else ''}"
                            f" {kbds(m, st, cmd)}</div>")
            if rows:
                w(f"<tr><td>{e(cat)}</td><td class=ops>{''.join(rows)}</td></tr>")
        w("</table>")
        if unassigned:
            w("<p class=note>キー未割り当て (または macOS では無効): "
              + "、".join(e(m.ja(x)) for x in unassigned) + "</p>")
        w("</div></div></section>")

    # --- キーから引く
    cols = []
    for st in MAIN_STATES:
        cols.append(st)
        if st in SUB_STATES:
            cols.append(SUB_STATES[st])
    used_cols = [s for s in cols if any(ks == s for ks, _ in m.keymap)]
    keys = sorted({k for (_, k) in m.keymap}, key=key_sort)
    w("<section id=keys><h2>キーから引く</h2>")
    w("<p class=note>行がキー、列が状態。セルはそのキーで実行される操作で、色は移った先の状態 (無色は同じ状態に留まる)。"
      "サブ状態の列の <span class=inh>灰色</span> は親状態の定義をそのまま使っているもの。空欄は未定義"
      " (DirectInput / Precomposition ではアプリへ渡り、Composition / Conversion では捨てられる)。</p>")
    w("<p class='legend note'>" + "".join(
        f"<span>{st_badge(s, '→ ' + s)}</span>" for s in MAIN_STATES) + "</p>")
    w("<table class=keys><tr><th>キー</th>" + "".join(
        f"<th>{e(s)}<br><span class=mute>{e(STATE_JA[s])}</span></th>" for s in used_cols) + "</tr>")
    for k in keys:
        cells = []
        for s in used_cols:
            own = m.keymap.get((s, k))
            cmd = m.effective(s, k)
            if not cmd:
                cells.append("<td></td>")
                continue
            parent = next((p for p, sub in SUB_STATES.items() if sub == s), s)
            d, _ = m.dest(parent, cmd)
            cls = f" class='cell-{STATE_COLOR[d]}'" if d else ""
            inh = "" if own else " class=inh"
            cells.append(f"<td{cls}><span{inh} title='{e(cmd)}'>{e(m.ja(cmd))}</span>"
                         f"{' →' + e(d) if d else ''}</td>")
        w(f"<tr><td class=k><kbd>{e(KEY_JA.get(k, k))}</kbd></td>{''.join(cells)}</tr>")
    w("</table></section></main></html>")
    return "\n".join(out)


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mozc", default=os.environ.get("MOZC"),
                    help="Mozc リポジトリ (既定: $MOZC または ghq の google/mozc)")
    ap.add_argument("--config", help="config1.db のパス (既定: 既知の場所を順に探す)")
    ap.add_argument("--keymap", default="current",
                    help="表示するキーマップ: current (config1.db の設定), "
                         + ", ".join(ov.BUILTIN_KEYMAPS) + ", または TSV ファイルのパス")
    ap.add_argument("-o", "--output", default=str(ROOT / "mozc/out/statemap.html"))
    args = ap.parse_args()

    if args.mozc:
        mozc = Path(args.mozc)
    else:
        try:
            ghq_root = subprocess.run(["ghq", "root"], capture_output=True, text=True,
                                      check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            ap.error("Mozc のソースが見つからない。--mozc か $MOZC で指定する")
        mozc = Path(ghq_root) / "github.com/google/mozc"
    src = mozc / "src"
    db = Path(args.config) if args.config else next((p for p in ov.DEFAULT_CONFIGS if p.exists()), None)
    rev = subprocess.run(["git", "-C", str(mozc), "log", "-1", "--format=%h %cs"],
                         capture_output=True, text=True).stdout.strip()

    builtin = lambda n: ov.parse_tsv((src / f"data/keymap/{n}.tsv").read_text(encoding="utf-8"))
    keymap_name = args.keymap
    if args.keymap == "current":
        _, current = ov.decode_config(src, db)
        sk = current.get("session_keymap")
        if sk == "CUSTOM" and current.get("custom_keymap_table"):
            keymap = ov.parse_tsv(current["custom_keymap_table"])
            keymap_name = "現在の設定 (CUSTOM)"
        else:
            name = {"KOTOERI": "kotoeri", "MSIME": "ms-ime", "ATOK": "atok",
                    "CHROMEOS": "chromeos"}.get(sk, "kotoeri")
            keymap = builtin(name)
            keymap_name = f"現在の設定 ({name})"
    elif args.keymap in ov.BUILTIN_KEYMAPS:
        keymap = builtin(args.keymap)
    else:
        keymap = ov.parse_tsv(Path(args.keymap).read_text(encoding="utf-8"))

    # KeyMapManager::LoadStream は TSV の後に "TextInput" (文字キー) -> InsertCharacter を暗黙に足す
    for st in ("Precomposition", "Composition", "Conversion"):
        keymap.setdefault((st, "TextInput"), "InsertCharacter")
    commands, noop = ov.keymap_commands(src)
    model = Model(commands, noop, keymap, ov.load_ts(src / "gui/config_dialog/keymap_ja.qtts"))
    unknown = sorted({c for c in keymap.values()} - {c for v in commands.values() for c in v})
    if unknown:
        print(f"warning: keymap.cc に無いコマンド: {', '.join(unknown)}", file=sys.stderr)
    ctx = {"model": model, "keymap_name": keymap_name, "mozc": str(mozc), "rev": rev,
           "db": str(db) if db else ""}
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(ctx), encoding="utf-8")
    print(f"generated: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
