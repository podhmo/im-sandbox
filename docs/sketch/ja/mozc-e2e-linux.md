# Linux (WSLg) での Mozc E2E テスト構築

> [!NOTE]
> [mozc-e2e-mac.md](./mozc-e2e-mac.md) の Linux 版。macOS が
> 「OSレベルのキー注入 + 実エディタ」1層なのに対し、Linux では
> 経路が複数あるため 3 層で検証する。環境構築は [mozc-wslg-setup.md](./mozc-wslg-setup.md)。

## 検証対象の経路

```
[実キー] → Windows → RDP → WSLg weston ─┬─ XWayland → GTK(x11)  ─┐
                                        └─ Wayland  → GTK(wayland)┤→ fcitx5 → mozc_server
[注入]   xdotool (XTEST) → XWayland ──────────────────────────┘        │
        アプリ内合成イベント → GTK(wayland) ────────────────────────────┘
        D-Bus 仮想 IC ────────────────────────────────────────────────
```

- 外部注入は X11 アプリにのみ可能 (WSLg に virtual-keyboard/evdev が無い)
- Wayland アプリはアプリ自身がイベントを合成する形で代替する
- 「fcitx5 → mozc のキー処理」は D-Bus の仮想 IC で直接・決定的に検証できる

## ファイル

| ファイル | 役割 |
|---|---|
| `tools/mozc_e2e_fcitx5.py` | D-Bus 仮想 IC ランナー。テストケースの定義本体 (`CASES`) |
| `tools/gtk_im_probe.py` | 観測用 GTK3 ミニエディタ。バッファ内容とキー到達をファイルに記録 |
| `tools/mozc_e2e_gui.py` | GUI ランナー。`x11` / `xim` / `wayland` モード。`CASES` を再利用 |
| `mozc/e2e.sh` | 学習隔離ラッパー。`linux` モードで上記ランナーを実行 |

## 実行方法

```sh
# fcitx5 が起動していること
fcitx5 -d --disable=wayland

# D-Bus 仮想 IC レベル (最速・最も決定的)
./mozc/e2e.sh linux custom      # カスタムキーマップ適用で 13/13
./mozc/e2e.sh linux default     # 既定キーマップ → 差分が検出される (4/13)

# GUI 経路: E2E_RUNNER で同じ隔離の下で実行
E2E_RUNNER="python3 $PWD/tools/mozc_e2e_gui.py x11"     ./mozc/e2e.sh linux custom
E2E_RUNNER="python3 $PWD/tools/mozc_e2e_gui.py xim"     ./mozc/e2e.sh linux custom
E2E_RUNNER="python3 $PWD/tools/mozc_e2e_gui.py wayland" ./mozc/e2e.sh linux custom
```

`e2e.sh` がやること (macOS 版と同じ設計):

1. `history_learning_level: NO_HISTORY` 付きの `config1.db` を生成して差し替え
2. 学習ファイル (`cform.db`, `segment.db`, `boundary.db`, `.history.db`) を退避
3. `mozc_server` を再起動してランナー実行、終了時にすべて復元

## 学習隔離で発見したこと (重要)

`NO_HISTORY` が効くのは `user_history_predictor` /
`user_segment_history_rewriter` / `user_boundary_history_rewriter` のみで、
**`cform.db` (文字種の学習) は対象外**。

実害として確認したもの:

- `C-q` で「ぬグ」をカタカナ確定した後、同一実行内の後続変換で
  `ぬぐ` が `ぬグ` と表示・確定されてしまう (実行内学習の漏れ)
- ファイル退避は「実行前の既存学習」を防ぐが、**実行中の新規学習は
  `NO_HISTORY` にしないと止まらない**。両方必要 (e2e.sh が両方やる)

## 判定方法の設計

- **確定文字列**: probe がバッファ変更のたびにファイルへ書き出す
- **分割確定** (`CommitOnlyFirstSegment`): `commit-buffer:` の書き込み回数で判定
- **アプリへの転送** (Precomposition の `C-p`/`C-a`、DIRECT モード):
  probe の keylog に `key:` 行として残るかで判定
  - D-Bus 版では `ProcessKeyEvent` の `accepted=False` で判定する。
    **`ForwardKey` シグナルは IM が新しいキーを押し込む別経路**であり、
    「消費せず転送したキー」はそこに現れない点に注意
- GUI で転送キーはバッファに挿入されるため、ケース側に
  `expect_commit_gui` で GUI 専用の期待値を持たせられる
  (例: directinput ケースは D-Bus では `あ`、GUI では `aあ`)

## 発見した経路差分: Ctrl+Shift+英字

X11 (xdotool/XTEST 経由) では `ctrl+shift+m` が keysym **`M`** として届き
(`ev.string='\r'`)、fcitx5 の `Key::normalize` で **Shift が落ちて
`Ctrl+m` (=Commit) として処理される**。mozc 側は `Ctrl+Shift+m` と
`Ctrl+m` を区別できない → `CommitOnlyFirstSegment` が `Commit` 扱いになる。

- 影響範囲: `Ctrl+Shift+<英字>` のすべて (`C-S-m`, `C-S-f`, `C-S-b`,
  `C-S-v`, `C-S-d` 等)。`Shift+Enter` は非英字なので Shift が保持され正常
- macOS (Cocoa) では修飾キーと文字が分離して届くためこの問題は起きない
- wayland モードの合成注入は keyval `m` + SHIFT state で届くため Shift が
  保持されて PASS するが、**実キーの Wayland 経路では同じ正規化が
  起きるはず** (注入手段が無く未検証)
- 対応: 該当ケースに `xfail_modes=["x11","xim"]` を付けて既知差分として記録。
  回避したければ `Shift+Enter` のような非英字修飾や、`Ctrl` 単体キーへの
  割り当てを検討する (キーマップの共有方針の問題)

## テスト結果 (カスタムキーマップ, NO_HISTORY)

| 層 | 結果 |
|---|---|
| D-Bus 仮想 IC | 13/13 PASS |
| GUI x11 (XTEST) | 13/13 (C-S-m は XFAIL=既知差分) |
| GUI xim | 13/13 (同上) |
| GUI wayland (アプリ内注入) | 13/13 全 PASS |

ネガティブコントロール: `./mozc/e2e.sh linux default` (mozc 既定キーマップ)
で 4/13 となり、カスタム設定の差分を正しく検出できることを確認済み。

## 既知の限界

- Wayland の**実キー**注入は不可能 (virtual-keyboard 無し)。アプリ内注入は
  「アプリ→immodule」以降の検証であり、キー到達部分は担保しない
- xdotool は XWayland 経由の XTEST。Windows 実キー → RDP → weston の
  区間は検証外 (WSLg 側の話なので対象外と割り切る)
- probe は GTK3。gedit (GTK4) でも日本語入力・保存は手動確認済みだが、
  GTK4 アプリ固有の差分はカバーしない
