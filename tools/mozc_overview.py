#!/usr/bin/env python3
"""Mozc の設定項目とキーマップを俯瞰する HTML を生成する。

情報源 (すべて Mozc のソースツリーと、現在の config1.db):
  - src/protocol/config.proto            設定項目・型・デフォルト値・コメント
  - src/gui/config_dialog/*              GUI 上のラベル (日本語訳) と選択肢
  - src/session/keymap.cc                状態ごとに使えるコマンド
  - src/gui/config_dialog/keymap_ja.qtts コマンド・状態の日本語名
  - src/data/keymap/*.tsv                組み込みキーマップ
  - src/composer/key_parser.cc           キー名
  - config1.db (protoc --decode)         現在の値・現在のキーマップ

usage: python3 -I tools/mozc_overview.py [--mozc DIR] [--config PATH] [-o OUT]

必要なもの: python3 (標準ライブラリのみ), protoc (現在値の表示に使う。無ければ省略), Mozc のソース
"""

from __future__ import annotations

import argparse
import codecs
import html
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIGS = [
    Path.home() / "Library/Application Support/Google/JapaneseInput/config1.db",
    Path.home() / "Library/Application Support/Mozc/config1.db",
    Path.home() / ".config/mozc/config1.db",
    Path.home() / ".mozc/config1.db",
]
STATES = ["DirectInput", "Precomposition", "Composition", "Suggestion",
          "Conversion", "Prediction", "ZeroQuerySuggestion"]
BUILTIN_KEYMAPS = ["kotoeri", "ms-ime", "atok", "chromeos"]


# ---------------------------------------------------------------- proto

def parse_proto(text: str) -> dict:
    """config.proto を素朴にパースする (ネストした message/enum, コメント, セクション見出し)."""
    lines = text.splitlines()
    root = {"name": "", "fields": [], "enums": {}, "messages": {}}
    stack = [root]
    comments: list[str] = []
    section = ""
    enum_stack: list[dict] = []
    pending_section: list[str] = []
    for raw in lines:
        line = raw.strip()
        if line.startswith("////"):
            # セクション区切り: 次の // 行を見出しにする
            pending_section = ["__start__"]
            comments = []
            continue
        if line.startswith("//"):
            c = line[2:].strip()
            if pending_section == ["__start__"]:
                if c:
                    pending_section = [c]
                continue
            if pending_section and not c:
                continue
            comments.append(c)
            continue
        if pending_section and pending_section != ["__start__"]:
            section = pending_section[0]
            pending_section = []
        if not line:
            comments = []
            continue
        m = re.match(r"message\s+(\w+)\s*\{", line)
        if m:
            msg = {"name": m.group(1), "fields": [], "enums": {}, "messages": {},
                   "comment": " ".join(comments)}
            stack[-1]["messages"][m.group(1)] = msg
            stack.append(msg)
            comments, section = [], ""
            continue
        m = re.match(r"enum\s+(\w+)\s*\{", line)
        if m:
            en = {"name": m.group(1), "values": [], "comment": " ".join(comments)}
            stack[-1]["enums"][m.group(1)] = en
            enum_stack.append(en)
            comments = []
            continue
        if line.startswith("}"):
            if enum_stack:
                enum_stack.pop()
            elif len(stack) > 1:
                stack.pop()
            comments = []
            continue
        if enum_stack:
            m = re.match(r"(\w+)\s*=\s*(-?\d+)", line)
            if m:
                enum_stack[-1]["values"].append(
                    {"name": m.group(1), "number": int(m.group(2)),
                     "comment": " ".join(comments) + _trailing(raw)})
            comments = []
            continue
        m = re.match(
            r"(optional|repeated|required)\s+([\w.]+)\s+(\w+)\s*=\s*(\d+)\s*(\[(.*?)\])?\s*;",
            line)
        if m:
            opts = m.group(6) or ""
            d = re.search(r"default\s*=\s*([^,\]]+)", opts)
            stack[-1]["fields"].append({
                "label": m.group(1), "type": m.group(2), "name": m.group(3),
                "number": int(m.group(4)),
                "default": d.group(1).strip() if d else None,
                "deprecated": "deprecated = true" in opts,
                "comment": " ".join(comments) + _trailing(raw),
                "section": section,
            })
            comments = []
            continue
        comments = []
    return root


def _trailing(raw: str) -> str:
    i = raw.find("//")
    return (" " + raw[i + 2:].strip()) if i >= 0 and raw.strip()[:2] != "//" else ""


# ---------------------------------------------------------------- GUI

def load_ts(path: Path) -> dict[str, str]:
    """Qt の翻訳ファイル (.qtts) を source -> translation の辞書にする."""
    if not path.exists():
        return {}
    out = {}
    for msg in ET.parse(path).getroot().iter("message"):
        s, t = msg.findtext("source"), msg.findtext("translation")
        if s and t:
            out[s] = t
    return out


def gui_info(src: Path) -> dict[str, dict]:
    """config field 名 -> {tab, label, options} (GUI で設定できるもの)."""
    cdir = src / "gui/config_dialog"
    cc = (cdir / "config_dialog.cc").read_text(encoding="utf-8")
    ja = load_ts(cdir / "config_dialog_ja.qtts")
    tr = lambda s: ja.get(s, s)

    widget_to_field: dict[str, str] = {}
    for m in re.finditer(r"SET_CHECKBOX\(\s*(\w+),\s*(\w+)\)", cc):
        widget_to_field[m.group(1)] = m.group(2)
    for m in re.finditer(r"SET_COMBOBOX\(\s*(\w+),\s*\w+,\s*(\w+)\)", cc):
        widget_to_field[m.group(1)] = m.group(2)
    # マクロを使わずに書かれているもの
    widget_to_field.update({
        "inputModeComboBox": "preedit_method",
        "localUsageDictionaryCheckBox": "information_list_config",
        "kutenCheckBox": "auto_conversion_key",
        "toutenCheckBox": "auto_conversion_key",
        "questionMarkCheckBox": "auto_conversion_key",
        "exclamationMarkCheckBox": "auto_conversion_key",
        "editKeymapButton": "custom_keymap_table",
        "editRomanTableButton": "custom_roman_table",
    })

    options: dict[str, list[str]] = {}
    for m in re.finditer(
            r'(\w+)->addItem\((?:tr\("((?:[^"\\]|\\.)*)"\)|QString::fromUtf8\("((?:[^"\\]|\\.)*)"\))',
            cc):
        w = m.group(1)
        text = m.group(2) if m.group(2) is not None else m.group(3)
        options.setdefault(w, []).append(tr(text))

    # .ui から widget のラベルとタブを取る
    tree = ET.parse(cdir / "config_dialog.ui")
    parent = {c: p for p in tree.iter() for c in p}

    def text_of(w):
        for prop in w.findall("property"):
            if prop.get("name") in ("text", "title"):
                return prop.findtext("string") or ""
        return ""

    def tab_of(w):
        n = w
        while n in parent:
            n = parent[n]
            if n.tag == "widget" and parent.get(n) is not None and \
                    parent[n].tag == "widget" and parent[n].get("class") == "QTabWidget":
                for a in n.findall("attribute"):
                    if a.get("name") == "title":
                        return tr(a.findtext("string") or "")
        return ""

    def group_of(w):
        n = w
        while n in parent:
            n = parent[n]
            if n.tag == "widget" and n.get("class") == "QGroupBox":
                return tr(text_of(n))
        return ""

    def label_of(w):
        t = text_of(w)
        if t:
            return tr(t)
        item = parent.get(w)
        if item is None or item.tag != "item":
            return ""
        layout = parent.get(item)
        row = item.get("row")
        for sib in layout.findall("item") if layout is not None else []:
            if sib.get("row") == row and sib.get("column") == "0":
                lw = sib.find("widget")
                if lw is not None and lw.get("class") == "QLabel":
                    return tr(text_of(lw))
        return ""

    info: dict[str, dict] = {}
    for w in tree.iter("widget"):
        name = w.get("name")
        field = widget_to_field.get(name)
        if not field:
            continue
        ent = info.setdefault(field, {"tab": tab_of(w), "group": group_of(w),
                                      "labels": [], "options": options.get(name, [])})
        lab = label_of(w)
        if lab and lab not in ent["labels"]:
            ent["labels"].append(lab)
    return info


# ---------------------------------------------------------------- keymap

def keymap_commands(src: Path) -> tuple[dict[str, list[str]], set[str]]:
    cc = (src / "session/keymap.cc").read_text(encoding="utf-8")
    consts = dict(re.findall(r'(kCommandString\w+)\[\]\s*=\s*"(\w+)"', cc))
    body = cc[cc.index("void KeyMapManager::InitCommandData()"):]
    body = body[:body.index("\n}\n")]
    out: dict[str, list[str]] = {}
    noop_on_mac: set[str] = set()
    for m in re.finditer(
            r"Register(Direct|Precomposition|Composition|Conversion)Command\(\s*"
            r'("(\w+)"|(kCommandString\w+)),\s*\w+::(\w+)\)', body):
        state = {"Direct": "DirectInput"}.get(m.group(1), m.group(1))
        name = m.group(3) or consts.get(m.group(4), m.group(4))
        if m.group(5) == "NONE":
            noop_on_mac.add(name)
        lst = out.setdefault(state, [])
        if name not in lst:
            lst.append(name)
    return out, noop_on_mac


def parse_tsv(text: str) -> dict[tuple[str, str], str]:
    out = {}
    for i, line in enumerate(text.splitlines()):
        if i == 0 or not line.strip() or line.startswith("#"):
            continue
        cols = [c for c in line.split("\t") if c]
        if len(cols) == 3:
            st = "DirectInput" if cols[0] == "Direct" else cols[0]
            out[(st, cols[1])] = cols[2]
    return out


def key_names(src: Path) -> tuple[list[str], list[str]]:
    cc = (src / "composer/key_parser.cc").read_text(encoding="utf-8")
    mods = re.search(r"kModifierKeyMap.*?\{(.*?)\}\);", cc, re.S)
    specials = re.search(r"kSpecialKeyMap.*?\{(.*?)\}\);", cc, re.S)
    f = lambda m: sorted(set(re.findall(r'\{"([^"]+)"', m.group(1)))) if m else []
    return f(mods), f(specials)


# ---------------------------------------------------------------- current config

def decode_config(src: Path, db: Path | None) -> tuple[str, dict]:
    if not db or not db.exists():
        return "", {}
    try:
        res = subprocess.run(
            ["protoc", "-I", str(src / "protocol"), "--decode=mozc.config.Config",
             "config.proto"],
            input=db.read_bytes(), capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"warning: protoc decode failed: {e}", file=sys.stderr)
        return "", {}
    text = res.stdout.decode("utf-8", "replace")
    values: dict = {}
    depth = 0
    for line in text.splitlines():
        s = line.strip()
        if s.endswith("{"):
            depth += 1
            continue
        if s == "}":
            depth -= 1
            continue
        if depth:
            continue
        m = re.match(r"(\w+): (.*)", s)
        if not m:
            continue
        k, v = m.groups()
        if v.startswith('"'):
            v = codecs.escape_decode(v[1:-1].encode("latin-1", "backslashreplace"))[0] \
                .decode("utf-8", "replace")
        values.setdefault(k, []).append(v)
    return text, {k: (v if len(v) > 1 else v[0]) for k, v in values.items()}


# ---------------------------------------------------------------- render

CSS = """
:root { --fg:#1d1d1f; --mute:#6e6e73; --bg:#fff; --line:#e5e5ea; --hl:#fff4c2; --acc:#0a66c2; --chg:#e8f5e9; }
@media (prefers-color-scheme: dark) { :root { --fg:#f2f2f7; --mute:#a1a1a6; --bg:#1c1c1e; --line:#38383a; --hl:#4a4020; --acc:#64a8ff; --chg:#1f3a24; } }
* { box-sizing: border-box; }
body { font: 14px/1.5 -apple-system, "Hiragino Sans", sans-serif; color: var(--fg); background: var(--bg); margin: 0; }
header { position: sticky; top: 0; background: var(--bg); border-bottom: 1px solid var(--line); padding: 10px 20px; z-index: 2; }
h1 { font-size: 18px; margin: 0 0 6px; }
nav a { margin-right: 14px; color: var(--acc); text-decoration: none; }
input[type=search] { width: 320px; padding: 4px 8px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); color: var(--fg); }
label.opt { margin-left: 12px; color: var(--mute); }
main { padding: 0 20px 40px; }
section { margin-top: 28px; }
h2 { font-size: 16px; border-bottom: 2px solid var(--line); padding-bottom: 4px; }
h3 { font-size: 14px; margin: 18px 0 6px; }
table { border-collapse: collapse; width: 100%; }
th, td { border-bottom: 1px solid var(--line); padding: 4px 8px; text-align: left; vertical-align: top; }
th { position: sticky; top: 86px; background: var(--bg); font-weight: 600; }
code { font: 12px ui-monospace, Menlo, monospace; }
.mute { color: var(--mute); font-size: 12px; }
.tag { display: inline-block; font-size: 11px; padding: 0 6px; border-radius: 8px; border: 1px solid var(--line); color: var(--mute); margin-right: 4px; }
.tag.gui { border-color: var(--acc); color: var(--acc); }
tr.changed td { background: var(--chg); }
td.diff { background: var(--hl); font-weight: 600; }
.cmd { white-space: nowrap; }
.sec { background: var(--line); font-weight: 600; }
details { margin: 8px 0; }
pre { background: var(--line); padding: 8px; overflow: auto; max-height: 400px; font-size: 12px; }
"""

JS = """
const q = document.getElementById('q'), onlyChanged = document.getElementById('onlyChanged');
function apply() {
  const s = q.value.toLowerCase();
  document.querySelectorAll('tr[data-s]').forEach(tr => {
    const hit = !s || tr.dataset.s.includes(s);
    const ch = !onlyChanged.checked || tr.classList.contains('changed') || tr.querySelector('td.diff');
    tr.style.display = hit && ch ? '' : 'none';
  });
}
q.addEventListener('input', apply); onlyChanged.addEventListener('change', apply);
"""


def e(s) -> str:
    return html.escape(str(s) if s is not None else "")


def render(ctx: dict) -> str:
    cfg = ctx["proto"]["messages"]["Config"]
    enums = cfg["enums"]
    gui = ctx["gui"]
    cur = ctx["current"]
    cmd_ja = ctx["keymap_ja"]
    out = []
    w = out.append
    w("<!doctype html><html lang=ja><meta charset=utf-8>")
    w("<title>Mozc 設定一覧</title><style>" + CSS + "</style>")
    w("<header><h1>Mozc 設定一覧</h1><nav>"
      "<a href='#config'>設定項目</a><a href='#keymap'>キーマップ比較</a>"
      "<a href='#commands'>コマンド一覧</a><a href='#keys'>キー名</a><a href='#raw'>現在の config</a></nav>"
      "<div style='margin-top:6px'><input id=q type=search placeholder='絞り込み (名前・説明・キー・コマンド)'>"
      "<label class=opt><input id=onlyChanged type=checkbox> 既定値から変更した項目のみ</label></div></header><main>")
    w(f"<p class=mute>生成元: <code>{e(ctx['mozc'])}</code> ({e(ctx['rev'])}) / "
      f"現在の設定: <code>{e(ctx['db'] or '(なし)')}</code></p>")

    # --- config fields
    w("<section id=config><h2>設定項目 (<code>mozc.config.Config</code>)</h2>")
    w("<p class=mute>GUI タグ付きは設定画面に対応する項目。それ以外は GUI では触れず、config1.db を直接書く必要がある。"
      "緑の行は現在の config1.db で値が明示されている項目。</p>")
    w("<table><tr><th>#</th><th>フィールド</th><th>型</th><th>既定値</th><th>現在値</th><th>GUI</th><th>説明 (proto のコメント)</th></tr>")
    section = None
    for f in sorted(cfg["fields"], key=lambda f: f["number"]):
        if f["section"] != section:
            section = f["section"]
            w(f"<tr class=sec><td colspan=7>{e(section or '-')}</td></tr>")
        t = f["type"]
        en = enums.get(t)
        type_html = e(t)
        if en:
            opts = gui.get(f["name"], {}).get("options", [])
            vals = []
            for i, v in enumerate(en["values"]):
                lab = f" = 「{e(opts[v['number']])}」" if 0 <= v["number"] < len(opts) else ""
                vals.append(f"<code>{e(v['name'])}</code>{lab}"
                            + (f" <span class=mute>{e(v['comment'])}</span>" if v["comment"].strip() else ""))
            type_html = f"<details><summary><code>{e(t)}</code></summary>{'<br>'.join(vals)}</details>"
        elif t in cfg["messages"]:
            sub = cfg["messages"][t]
            type_html = (f"<details><summary><code>{e(t)}</code></summary>" +
                         "<br>".join(f"<code>{e(x['name'])}</code>: {e(x['type'])}"
                                     f" (既定 {e(x['default'])}) <span class=mute>{e(x['comment'])}</span>"
                                     for x in sub["fields"]) + "</details>")
        g = gui.get(f["name"])
        gui_html = ""
        if g:
            gui_html = (f"<span class='tag gui'>GUI</span>{e(g['tab'])}"
                        + (f" › {e(g['group'])}" if g["group"] else "")
                        + (f"<br><b>{e(' / '.join(g['labels']))}</b>" if g["labels"] else ""))
        v = cur.get(f["name"])
        if f["name"] in ("custom_keymap_table", "custom_roman_table") and v:
            v = f"({len(v.splitlines())} 行) → キーマップ比較を参照"
        tags = ""
        if f["deprecated"]:
            tags += "<span class=tag>deprecated</span>"
        if f["label"] == "repeated":
            tags += "<span class=tag>repeated</span>"
        search = " ".join([f["name"], f["comment"], gui_html, str(v or "")]).lower()
        cls = " class=changed" if f["name"] in cur and f["name"] != "general_config" else ""
        w(f"<tr{cls} data-s='{e(search)}'><td>{f['number']}</td><td><code>{e(f['name'])}</code> {tags}</td>"
          f"<td>{type_html}</td><td><code>{e(f['default'] if f['default'] is not None else '')}</code></td>"
          f"<td><code>{e(v if not isinstance(v, list) else ', '.join(v))}</code></td>"
          f"<td>{gui_html}</td><td>{e(f['comment'])}</td></tr>")
    w("</table></section>")

    # --- keymap comparison
    km = ctx["keymaps"]
    cols = list(km.keys())
    w("<section id=keymap><h2>キーマップ比較</h2>")
    w("<p class=mute>状態ごとに、キー → コマンド。黄色のセルは「現在」が kotoeri (macOS 既定) と異なる箇所。"
      "Suggestion / Prediction に無いキーはそれぞれ Composition / Conversion の定義が使われる。"
      "Precomposition で未定義のキーはアプリへ渡り、Composition/Conversion で未定義のキーは IME が握りつぶす。</p>")
    state_ja = ctx["state_ja"]
    for st in STATES:
        keys = sorted({k for m in km.values() for (s, k) in m if s == st},
                      key=lambda k: (k.lower().replace("ctrl ", "~").replace("shift ", "~~"), k))
        if not keys:
            continue
        w(f"<h3>{e(st)} <span class=mute>{e(state_ja.get(st, ''))}</span></h3>")
        w("<table><tr><th>キー</th>" + "".join(f"<th>{e(c)}</th>" for c in cols) + "</tr>")
        for k in keys:
            cells = []
            base = km.get("kotoeri", {}).get((st, k))
            for c in cols:
                cmd = km[c].get((st, k))
                diff = c == "現在" and cmd != base
                txt = (f"<code>{e(cmd)}</code><br><span class=mute>{e(cmd_ja.get(cmd, ''))}</span>"
                       if cmd else "<span class=mute>-</span>")
                cells.append(f"<td class='cmd{' diff' if diff else ''}'>{txt}</td>")
            search = " ".join([st, k] + [str(km[c].get((st, k), "")) for c in cols]).lower()
            w(f"<tr data-s='{e(search)}'><td><code>{e(k)}</code></td>{''.join(cells)}</tr>")
        w("</table>")
    w("</section>")

    # --- commands
    w("<section id=commands><h2>状態ごとに使えるコマンド</h2>")
    w("<p class=mute><code>src/session/keymap.cc</code> の <code>InitCommandData()</code> から抽出。"
      "Suggestion / ZeroQuerySuggestion は Composition / Precomposition、Prediction は Conversion のコマンドを使う。"
      "<span class=tag>macOS では無効</span> は Apple 系 OS では NONE (何もしない) に登録されるもの。</p>")
    w("<table><tr><th>状態</th><th>コマンド</th><th>日本語名 (設定画面)</th><th>使っているキー (現在)</th></tr>")
    current_map = km.get("現在") or km.get("kotoeri", {})
    for st, names in ctx["commands"].items():
        for n in names:
            used = [k for (s, k), c in current_map.items()
                    if c == n and (s == st or (st == "Composition" and s == "Suggestion")
                                   or (st == "Conversion" and s == "Prediction")
                                   or (st == "Precomposition" and s == "ZeroQuerySuggestion"))]
            noop = "<span class=tag>macOS では無効</span>" if n in ctx["noop_on_mac"] else ""
            search = " ".join([st, n, cmd_ja.get(n, ""), *used]).lower()
            w(f"<tr data-s='{e(search)}'><td>{e(st)}</td><td><code>{e(n)}</code> {noop}</td>"
              f"<td>{e(cmd_ja.get(n, ''))}</td><td>{'<br>'.join('<code>' + e(u) + '</code>' for u in used)}</td></tr>")
    w("</table></section>")

    # --- key names
    mods, specials = ctx["keys"]
    w("<section id=keys><h2>キー名</h2><p class=mute>"
      "<code>src/composer/key_parser.cc</code> より。大文字小文字は区別しない。"
      "書式は <code>Ctrl Shift f</code> のように空白区切り。</p>")
    w("<h3>修飾キー</h3><p>" + " ".join(f"<code>{e(x)}</code>" for x in mods) + "</p>")
    w("<h3>特殊キー</h3><p>" + " ".join(f"<code>{e(x)}</code>" for x in specials) + "</p></section>")

    # --- raw
    w("<section id=raw><h2>現在の config1.db (protoc --decode)</h2>")
    raw = ctx["raw"]
    w(f"<pre>{e(raw) if raw else '(config1.db がないか、デコードできなかった)'}</pre></section>")
    w("</main><script>" + JS + "</script></html>")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mozc", default=os.environ.get("MOZC"),
                    help="Mozc リポジトリ (既定: $MOZC または ghq の google/mozc)")
    ap.add_argument("--config", help="config1.db のパス (既定: 既知の場所を順に探す)")
    ap.add_argument("-o", "--output", default=str(ROOT / "mozc/out/overview.html"))
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
    db = Path(args.config) if args.config else next((p for p in DEFAULT_CONFIGS if p.exists()), None)

    rev = subprocess.run(["git", "-C", str(mozc), "log", "-1", "--format=%h %cs"],
                         capture_output=True, text=True).stdout.strip()
    raw, current = decode_config(src, db)
    keymap_ja = load_ts(src / "gui/config_dialog/keymap_ja.qtts")
    keymaps = {name: parse_tsv((src / f"data/keymap/{name}.tsv").read_text(encoding="utf-8"))
               for name in BUILTIN_KEYMAPS}
    if current.get("session_keymap") == "CUSTOM" and current.get("custom_keymap_table"):
        keymaps["現在"] = parse_tsv(current["custom_keymap_table"])
    elif current.get("session_keymap"):
        name = {"KOTOERI": "kotoeri", "MSIME": "ms-ime", "ATOK": "atok", "CHROMEOS": "chromeos"} \
            .get(current["session_keymap"])
        if name:
            keymaps["現在"] = dict(keymaps[name])
    commands, noop = keymap_commands(src)
    ctx = {
        "mozc": str(mozc), "rev": rev, "db": str(db) if db else "",
        "proto": parse_proto((src / "protocol/config.proto").read_text(encoding="utf-8")),
        "gui": gui_info(src), "current": current, "raw": raw,
        "keymap_ja": keymap_ja, "keymaps": keymaps,
        "state_ja": {s: keymap_ja.get(s, "") for s in STATES},
        "commands": commands, "noop_on_mac": noop, "keys": key_names(src),
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(ctx), encoding="utf-8")
    print(f"generated: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
