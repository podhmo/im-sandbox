# WSLg 環境で Mozc による日本語入力を有効にする

> [!NOTE]
> このドキュメントは WSLg 有効な WSL2 Ubuntu 上で、GUI エディタが Mozc 経由で
> 日本語入力できる状態への到達手順の記録。テスト方法は [mozc-e2e-linux.md](./mozc-e2e-linux.md)、
> Emacs 固有の設定は [mozc-emacs.md](./mozc-emacs.md)。

## 目的

WSLg (Wayland + XWayland) 環境で GTK の GUI エディタ (gedit 等) に
fcitx5 + Mozc で日本語入力する。キーマップは本リポジトリのカスタム
Emacs 風キーマップ (`mozc/keymap.tsv`) を使う。

## 環境

- Ubuntu 26.04 on WSL2 (`6.18.x-microsoft-standard-WSL2`)
- WSLg: weston が `wayland-0` と XWayland (`DISPLAY=:0`) を提供
- ユーザー `po`、systemd 有効、`DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus`

## インストールしたパッケージ

```sh
sudo apt install fcitx5 fcitx5-mozc fcitx5-frontend-all gedit protobuf-compiler
```

- `fcitx5-frontend-all`: GTK3/GTK4 immodule を含む
- `protobuf-compiler`: `mozc/build.sh` が `config1.db` 生成に使う
- fcitx5-mozc は `mozc_server` (`/usr/lib/mozc/mozc_server`) を介して
  mozc を動かす。設定は `~/.config/mozc/config1.db`

## WSLg の制約 (重要)

weston が提供する IM 関連プロトコル (レジストリ列挙で確認):

| プロトコル | 有無 | 影響 |
|---|---|---|
| `zwp_input_method_v1` | あり | ただし fcitx5 の wayland アドオンが bind すると失敗して **fcitx5 ごと落ちる** |
| `zwp_text_input_manager_v1` | あり | text-input-v1 のみ。v3 (現行主流) は無し |
| `zwp_virtual_keyboard_v1` | **無し** | Wayland クライアントへの外部キー注入手段が存在しない |
| evdev 経由 | **無し** | weston は RDP バックエンド。ydotool 等も不可 |

結論:

1. **fcitx5 は必ず `--disable=wayland` で起動する**。裸の `fcitx5` は
   wayland アドオンで `zwp_input_method_v1` への bind に失敗して終了する。
2. キー注入は X11 アプリへの `xdotool` (XTEST) のみ可能。
   Wayland アプリへはアプリ自身が合成イベントを作るしかない。
3. Wayland クライアントでも実際の IM 接続は **GTK immodule → D-Bus
   (dbusfrontend)** であり、fcitx5 の wayland アドオンは要らない
   (むしろ起動を妨げるだけ)。

## 起動と永続化

### fcitx5 の起動

```sh
fcitx5 -d --disable=wayland
```

### D-Bus activation の罠

`/usr/share/dbus-1/services/org.fcitx.Fcitx5.service` が
`Exec=/usr/bin/fcitx5` で登録されている。何かがサービス名を要求すると
**オプション無しの fcitx5 が自動起動して落ちる**。ユーザ側で上書き:

`~/.local/share/dbus-1/services/org.fcitx.Fcitx5.service`:

```ini
[D-BUS Service]
Name=org.fcitx.Fcitx5
Exec=/usr/bin/fcitx5 --disable=wayland
```

### 環境変数と自動起動

- `~/.config/environment.d/90-fcitx5.conf` (systemd user 経由で RAIL/
  .desktop 起動のアプリに届く):

```conf
GTK_IM_MODULE=fcitx
QT_IM_MODULE=fcitx
XMODIFIERS=@im=fcitx
```

- `~/.profile` (シェルから起動する GUI アプリ用 + fcitx5 自動起動):

```sh
export GTK_IM_MODULE=fcitx
export QT_IM_MODULE=fcitx
export XMODIFIERS=@im=fcitx
if [ -n "$DISPLAY" ] && ! pgrep -x fcitx5 >/dev/null 2>&1; then
    fcitx5 -d --disable=wayland >/dev/null 2>&1
fi
```

- zsh は `~/.zprofile` しか読まないので `~/.zprofile` から `.profile` を source する。

WSLg には XDG autostart の実行系が無いため autostart.desktop は効かない。

## Mozc のカスタム設定

```sh
./mozc/build.sh          # keymap.tsv + config.base.textproto → out/config1.db
./mozc/apply.sh linux    # ~/.config/mozc/config1.db へ適用 + mozc_server 再起動
```

Linux の mozc 設定は `~/.config/mozc/config1.db`
(upstream の優先順: `~/.mozc` > `$XDG_CONFIG_HOME/mozc` > `~/.config/mozc`)。
適用後は `mozc_server` を kill して次回接続時に新設定で起動し直させる。

## 使い方上の注意

- **新規入力コンテキストは `keyboard-us` 非活性で始まる**。fcitx5 profile の
  `DefaultIM=mozc` は「トリガーで切り替わる先」であり新規 IC の初期 IM ではない。
  実使用でも e2e でも `Ctrl+Space` (TriggerKey) で mozc を活性化する。
- fcitx5-mozc は mozc 本体の `IsDirectModeCommand` を使うため、DirectInput
  キーマップで `IMEOn` に割り当てたキー (半角/全角等) だけが DIRECT モードで
  mozc に送られ、残りはアプリに素通しする — macOS 版と同じセマンティクス。

## 確認

gedit を対象に実機経路 (xdotool → XWayland → gedit → fcitx5 → mozc) で
`あいうえお` の確定と保存を確認済み:

```sh
printf '' > /tmp/t.txt
GDK_BACKEND=x11 GTK_IM_MODULE=fcitx gedit /tmp/t.txt &
xdotool search --name "t.txt" | tail -1 | xargs xdotool windowactivate --sync
xdotool key ctrl+space            # mozc 活性化
xdotool type --delay 60 aiueo     # 読み入力 (preedit)
xdotool key Return                # 確定
xdotool key ctrl+s                # 保存 → ファイルに「あいうえお」
```
