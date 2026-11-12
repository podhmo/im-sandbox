# 次のセッションで渡すプロンプト

以下を新しいセッションにそのまま貼り付けて再開する。

---

Emacs風の日本語入力キーマップ（Mozc / Google日本語入力）の作業の続きをしたい。前回（2026-11-13）までに macOS でのキーの割り当てはほぼ決まった。残りの作業を進めてほしい。

## まず読むもの

- `docs/ja/article.html`: どの状況でどう動くべきかを整理した記事。決めたことはここが正（q-and-a.md や kotoeri.tsv ではない）。原則 P1〜P6、状態ごとの操作、文字幅（4.5）、衝突・懸念のメモ（7章 C1〜C19）がある
- `docs/ja/TODO.html`: これから決めること・作ること・確かめること。完了は `class="done"`
- `mozc/keymap.tsv`: キーマップ全体（kotoeri.tsv への追記ではなく自前で全部書く。P5）
- `mozc/config.base.textproto`: キーマップ以外の設定（文字幅のルール `character_form_rules` など）
- `docs/sketch/ja/mozc-customization.md`、`docs/sketch/ja/mozc-e2e-mac.md`: 設定の仕組みと E2E の調査メモ
- Mozc のソースは `~/ghq/github.com/google/mozc`（挙動の根拠はソースを読んで確かめる）

## 作業の進め方（前回のやり方）

- 決めたこと・わかったことは、そのつど `article.html` と `TODO.html` に反映する。状態は「決定 / 案 / 未定」のバッジで表す。衝突や懸念は article.html の 7章に C番号で追記する
- 設定を変えたら `./mozc/build.sh && ./mozc/apply.sh` で Google日本語入力に適用し、私が実機で試す。確認できたら TODO の項目を done にする
- 状態遷移の確認には `python3 -I tools/mozc_statemap.py --keymap mozc/keymap.tsv -o mozc/out/statemap.draft.html`
- コミットは私が頼んだときだけ

## 残りの作業

### 1. E2E を今のキーマップに合わせる（最初にやる）

`tools/mozc_e2e_mac.swift` のケースは古いキーマップ前提のままになっている。

- カタカナ表示に `C-k` を使っているケース（「C-S-b で縮める + C-e / C-a で文節移動」「C-f / C-b で文節移動」）は、今は `C-q` に変わったので直す
- 遷移3方向（進む・抜ける・戻る）のケースを追加する。例: 読み入力中の `C-n` で予測変換に入る、変換中の `C-g` で読みに戻り、もう一度 `C-g` で読みが消える、`C-S-m` / `S-Enter` で先頭の文節だけ確定する、`C-i` / `C-o` で文節の伸縮
- 実行は `./mozc/e2e.sh`（アクセシビリティ権限のある端末から。私が実行する）

### 2. macOS で未確認のもの（TODO.html「確かめること（macOS）」）

- `C-S-Space`（再変換）が IME に届くか、ほかのショートカットと衝突しないか（範囲選択して `C-S-Space` で再変換できることは確認済み）
- `C-j` / `C-q` / `C-l` と `C-v` / `C-S-v` を実機で試す
- 変換中の Tab（文節を縮める）に違和感がないか
- 入力文字なしの状態で Ctrl キーがブラウザー（Firefox / Chrome）のテキストエリアに渡るか
- 選択がないときの `Reconvert` のキーがアプリに渡るか
- TODO.html に残っている古い項目（「取り消せる確定がないときに Undo のキーを…」など、入力文字なしの Undo を外したので不要になったもの）を整理する

### 3. まだ決めていないこと（TODO.html「決めること」）

- F6〜F10、Eisu、Hankaku/Zenkaku など Ctrl 系以外のキーをどこまで引き継ぐか
- Suggestion / Prediction に独自の定義を持たせない方針でよいか（今は Suggestion の Down / Shift Enter、Prediction の C-Delete / C-S-d だけ）
- 英字・記号の全角 / 半角（数字、数字の後の . , 、<>=+-/* は半角にした。英字や ?! () などは既定のまま）

### 4. Linux / WSLg / Windows（TODO.html の該当節）

- Fcitx5 + Mozc で `C-i` / `C-o`、`C-S-b` / `C-S-f`、`C-S-m` などが届くか
- Fcitx5 で `C-i` と Tab、`C-m` と Enter、`C-h` と Backspace が区別されるか（P6 の前提）
- WSLg で Windows 側のショートカットに取られずに Linux アプリまで届くキー
- Windows の Google日本語入力に同じ `config1.db` を適用できるか
- Linux 用の build / apply スクリプト（`~/.config/mozc/config1.db` など、パスとプロセス名の調査から）
- Firefox の `about:keyboard` で Ctrl+N を外せるか

### 5. 運用

- Google日本語入力の設定画面で「OK」を押すと `config1.db` が上書きされる問題への対処（article.html C11）

### 6. IME の外（任意）

- undo / redo を Emacs 風のキーにするか（macOS なら `DefaultKeyBinding.dict`。article.html C18）

## 前回わかった注意点

- `custom_keymap_table` の 1行目はヘッダーとして読み飛ばされる。同じ状態・キーは後の行が勝つ
- `character_form_rules` は1つでも書くと既定のルールが全部使われなくなるので、全グループを書く
- 入力文字なしの状態で打った空白はすぐ確定する（またはアプリに渡る）ので、後から `C-l` などで変えられない
- macOS では Enter で確定した後の Undo（確定の取り消し）は効かなかった。入力文字なしの `C-g` は何もせずアプリに渡す
- Mozc では「-」の全角形が U+2212 MINUS SIGN になる
- 範囲選択の `C-g` での解除は IME では無理なので諦めた（C17）。Space での再変換も無理（C16）
