# GUI Emacs で Mozc による日本語入力を使う

> [!NOTE]
> WSLg 上の GUI Emacs で mozc 入力を使う方法の調査記録。
> 基盤となる環境は [mozc-wslg-setup.md](./mozc-wslg-setup.md)、
> テスト手法は [mozc-e2e-linux.md](./mozc-e2e-linux.md) を参照。

## 前提

- Emacs: `~/.nix-profile/bin/emacs` (GNU Emacs 30.2, GTK3 ビルド, `XIM` あり)
- `~/.emacs.d` → `~/ghq/github.com/podhmo/emacs-sandbox/rebirth`
  (現状の日本語入力は ddskk; mozc 設定は skk の代替として同じ場所に書ける)
- fcitx5 + fcitx5-mozc は setup ドキュメント通り起動済み、
  カスタムキーマップは `~/.config/mozc/config1.db` に適用済み

## 経路の選択肢

emacs で mozc を使う方法は2つある。

| 経路 | 接続 | 要パッケージ | 特徴 |
|---|---|---|---|
| **[A] XIM 経由** | emacs →(XIM)→ fcitx5 → mozc_server | なし | 他アプリと同じ fcitx5。トリガーは C-Space。環境変数だけで有効 |
| **[B] mozc.el 直接** | emacs → mozc_emacs_helper → mozc_server | `emacs-mozc` | emacs の input-method。preedit/候補は emacs 内に描画。`-nw` でも使える |

どちらも同じ `mozc_server` + `config1.db` を使うため、
本リポジトリのカスタム Emacs 風キーマップがそのまま効く。

## [A] XIM 経路 (追加パッケージ不要、検証済み)

emacs 起動時に `XMODIFIERS` を指定するだけ (elisp 側の設定は不要):

```sh
XMODIFIERS=@im=fcitx GTK_IM_MODULE=fcitx emacs /tmp/test.txt &
```

- XIM フィルタは emacs のキーバインド解決より**前段**で動くため、
  `C-Space` は set-mark ではなく fcitx5 のトリガーとして mozc を活性化する
- 変換中の `C-g` も emacs の `keyboard-quit` ではなく mozc の Cancel に届く
  (カスタムキーマップ通りに動作することを確認済み)
- 検証結果: 読み入力→確定 `あいうえお`、変換→確定、C-g キャンセル、すべて実機経路で PASS

シェルに常設する場合 (`~/.profile`、コメントとして残す):

```sh
# export XMODIFIERS=@im=fcitx
# export GTK_IM_MODULE=fcitx
# (environment.d 側に書けば systemd 経由のアプリにも効く)
```

注意: GUI 起動時にだけ効かせたいので `.zshrc` ではなく login 系ファイルか
`environment.d` に置くのがよい。

## [B] mozc.el 経路 (`emacs-mozc-bin` + deb から取り出した mozc.el)

`emacs-mozc` パッケージは依存で **apt 版 emacs 本体**を引き込むため使わない。
helper バイナリだけ入れて、mozc.el は deb を展開して取り出す:

```sh
sudo apt install emacs-mozc-bin    # mozc_emacs_helper のみ (依存は mozc-server 等)
# mozc.el だけ取り出す (sudo 不要):
cd /tmp && apt download emacs-mozc && dpkg -x emacs-mozc_*_amd64.deb emacs-mozc-x
mkdir -p ~/.local/share/emacs/site-lisp
cp -r /tmp/emacs-mozc-x/usr/share/emacs/site-lisp/emacs-mozc \
      ~/.local/share/emacs/site-lisp/mozc
```

検証済み (`emacs -Q -l tools/emacs-mozc-init.el`):
`C-\` で `current-input-method` = `japanese-mozc` になり、
読み→確定 `あいうえお`、`kanji`+Space+Enter → `感じ`、
`aiu`+C-g+`e`+Enter → `え` (カスタムキーマップの Cancel が emacs の
keyboard-quit ではなく mozc に届く) を実機経路で確認。
モードラインには `[Mozc]` インジケータが出る。

### 最小検証 (emacs -Q)

`tools/emacs-mozc-init.el` を用意してある:

```sh
emacs -Q -l tools/emacs-mozc-init.el /tmp/test.txt &
# C-\ (toggle-input-method) で mozc 有効化 → 読み入力 → Enter 確定
```

### rebirth (~/.emacs.d) に入れる場合の設定例

`init.el` の `my:after-initialize--windows` (gnu/linux=WSL の分岐) にある
skk ブロックと同じ位置に置ける。コメントとして残す:

```elisp
;; mozc (fcitx を介さず mozc_server に直接接続する経路)
;; need: sudo apt install emacs-mozc-bin + deb から mozc.el を取り出す
;;       (emacs-mozc パッケージ自体は apt emacs を依存で引くので入れない)
;; (add-to-list 'load-path "~/.local/share/emacs/site-lisp/mozc")
;; (when (locate-library "mozc")
;;   (require 'mozc)
;;   (setq default-input-method "japanese-mozc") ; C-\ でトグル
;;   ;; 候補表示: 'echo-area (既定) / 'overlay / 'popup
;;   ;; (setq mozc-candidate-style 'overlay)
;;   )
```

skk との併用は `default-input-method` が1つしか持てないので
`C-x j` を `skk-mode`、`C-\` を mozc という住み分けか、
どちらか一方を選ぶ形になる。

## 動作確認の手段

### バッファ内容の確認 (文字列レベル)

emacs を `(server-start)` 付きで起動し、emacsclient から読む:

```sh
emacs -Q --eval '(server-start)' /tmp/test.txt &
xdotool search --name test.txt | tail -1 | xargs xdotool windowactivate --sync
xdotool key ctrl+space          # [A] の場合 mozc 活性化
xdotool type --delay 60 aiueo
xdotool key Return
emacsclient --eval '(with-current-buffer "test.txt" (buffer-string))'
# => "あいうえお"
```

### 画面キャプチャ (見た目の確認)

emacs-sandbox の `tools/mac-shot` (macOS `screencapture`) と同じ役割で
`tools/x11-shot` を用意。X11/XWayland クライアントの窓を PNG で撮る:

```sh
sudo apt install maim   # 必要
tools/x11-shot <pid> /tmp/emacs.png
```

`maim -i <windowid>` を使う。対象 pid の最大ウィンドウを `xdotool search --pid`
で探し、前面に出してから撮る設計は mac-shot と同じ。
wayland ネイティブ窓は xdotool に見えないため X11 クライアント限定
(nix の GTK3 emacs は非 pgtk なので X11 で動く)。

```sh
emacs -Q -l tools/emacs-mozc-init.el /tmp/t.txt &
xdotool type --delay 60 kanji; xdotool key space   # 変換中に
./tools/x11-shot "$(xdotool search --name t.txt | tail -1 | \
                   xargs xdotool getwindowpid)" /tmp/emacs.png
# → バッファ内に変換中の「感じ」とモードライン [Mozc] が写る
```
