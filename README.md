# im-sandbox

macOS・Windows・Linux（主に WSLg）で、似たような使用感で IME を使えるようにするための個人的な実験場。

目指すのは **Emacs 風キーバインドによる日本語入力の統一**。変換エンジンを共通化するのではなく、「キー入力の解釈」と「入力状態に応じた操作」を共通化する。IME の自作はせず、Mozc 系（Google日本語入力 / Fcitx5 + Mozc）の設定機構を使って、キーマップをリポジトリ管理し、生成・適用・E2E 検証までを自動化している。

## 方針

- 変換エンジンは既存のもの（Google日本語入力 / Mozc）をそのまま使う。共通 IME を作らない
- Mozc の `session_keymap: CUSTOM` と `custom_keymap_table` に、**自前の TSV を丸ごと書く**（kotoeri への追記ではない）
- キーマップの仕様は `docs/ja/article.html` が正。原則 P1〜P6（例: 入力文字なしの Ctrl 系はアプリへ渡す、Option 系は入れない、先頭文節だけ確定するキーを持つ）に従う
- 設定は `config1.db`（protobuf バイナリ）を `protoc --encode` で生成し、GUI を操作せずに適用する
- 各 OS で E2E テストを用意し、キーマップ変更の動作を自動検証する

詳細な検討過程は [docs/ja/q-and-a.md](docs/ja/q-and-a.md)（Q1〜Q11）を参照。

## ディレクトリ構成

```
mozc/          キーマップ・設定の生成と適用
  keymap.tsv            Emacs 風キーマップ本体（状態 <TAB> キー <TAB> コマンド）
  config.base.textproto キーマップ以外の設定（文字種ルールなど）
  build.sh / build.ps1  config1.db（protobuf バイナリ）を生成
  apply.sh / apply.ps1  config1.db を各 OS の設定ディレクトリに配置し変換サーバーを再起動
  e2e.sh / e2e.ps1      学習無効の一時設定で E2E を実行（終了時に設定を元へ戻す）
  clear-learning.sh / .ps1  学習データの退避（学習の影響を排除したいとき用）
  third_party/mozc/protocol/config.proto  Windows ビルド用の proto 定義

tools/         E2E・検証・可視化ツール
  mozc_e2e_mac.swift    macOS: TextEdit に実キーを送って検証
  mozc_e2e_win.cs       Windows: WPF プローブに実キーを送って検証
  mozc_e2e_fcitx5.py    Linux: fcitx5 の D-Bus 仮想 IC で検証（GUI 不要・決定的）
  mozc_e2e_gui.py       Linux: 実 GTK アプリ経由の検証（x11 / xim / wayland の3経路）
  gtk_im_probe.py       観測用ミニエディタ（バッファ・キーイベントを記録）
  mozc_overview.py      設定項目とキーマップを俯瞰する HTML を生成
  mozc_statemap.py      状態遷移図つきのキーマップ HTML を生成
  probe_ime_on.cs       Windows で IME オンの方法を試す小さなテスト
  emacs-mozc-init.el    GUI Emacs で mozc 入力を試す最小 init（mozc.el 直接 / XIM の2経路）
  x11-shot              X11 ウィンドウのスクリーンショット

docs/ja/       仕様と TODO（日本語）
  article.html            キーマップの仕様書（これが正）
  TODO.html               決めること・作ること・確かめること
  q-and-a.md              設計上の問答（目的・方針の根拠）
  next-session-prompt.md  作業再開用のプロンプト

docs/sketch/ja/  調査メモ（日本語）
  mozc-customization.md   config1.db / キーマップの仕組み（Mozc ソース由来）
  mozc-e2e-mac.md         macOS の E2E 構築
  mozc-e2e-windows.md     Windows の設定適用と E2E
  mozc-e2e-linux.md       Linux (WSLg) の E2E 構築（D-Bus / X11 / Wayland の3層）
  mozc-wslg-setup.md      WSLg で fcitx5 + Mozc を有効にする手順
  mozc-emacs.md           GUI Emacs での入力方法
```

## 設定の生成と適用

### macOS / Linux（シェル）

```sh
./mozc/build.sh            # out/config1.db を生成
./mozc/apply.sh            # Google日本語入力に適用（既定）
./mozc/apply.sh mozc       # OSS Mozc に適用
./mozc/apply.sh linux      # Linux の ~/.config/mozc に適用
```

### Windows（PowerShell）

```powershell
.\mozc\build.ps1
.\mozc\apply.ps1           # Google日本語入力に適用（既定）
.\mozc\apply.ps1 mozc      # OSS Mozc に適用
```

適用後は変換サーバーが再起動され、次回の入力から新しいキーマップが有効になる。既存の `config1.db` は自動でバックアップされる。

注意: 適用後に GUI の設定画面で「OK」を押すと `config1.db` が上書きされる。

## E2E テスト

学習を無効化した一時設定（`history_learning_level: NO_HISTORY`）で実行し、終了時に元の設定へ戻す。

```sh
./mozc/e2e.sh                     # macOS: カスタムキーマップで実行
./mozc/e2e.sh kotoeri             # macOS: 既定キーマップ（差分検出の確認用）
./mozc/e2e.sh linux               # Linux: fcitx5 + D-Bus 仮想 IC
./mozc/e2e.sh linux -- x11        # Linux: GUI 経路を指定して実行
```

```powershell
.\mozc\e2e.ps1                    # Windows: カスタムキーマップで実行
.\mozc\e2e.ps1 default            # Windows: 既定キーマップ（差分検出の確認用）
```

`--only <case名の一部>` でケースを絞れる。

- macOS: 実行するターミナルにアクセシビリティ権限が必要。実行中は TextEdit が最前面になる
- Linux: `fcitx5 -d --disable=wayland` が起動していること

## 必要なもの

| 環境 | 依存 |
| --- | --- |
| 共通 | `protoc`、Mozc のソース（`ghq get google/mozc`。`MOZC` 環境変数で別の場所も指定可） |
| macOS | Google日本語入力（`brew install --cask google-japanese-ime`）または自前ビルドの Mozc |
| Windows | Google日本語入力、`protoc`（`winget install Google.Protobuf`） |
| Linux | fcitx5 + mozc（WSLg では `fcitx5 -d --disable=wayland`） |
| GUI E2E (Linux) | `xdotool` `maim`（X11 経路のみ） |

## 状態

実験中。macOS・Windows（Google日本語入力）では設定の生成・適用と E2E が動作し、Linux (WSLg) でも fcitx5 + Mozc の E2E 環境が構築済み。決めていないこと・確かめていないことは `docs/ja/TODO.html` に残っている。
