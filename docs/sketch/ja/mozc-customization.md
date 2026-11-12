# Mozcのカスタマイズ調査メモ（macOS・GUIを使わない設定適用）

調査日: 2026-11-13
参照ソース: google/mozc master (`a4541df`, 2026-11-09)

目的は [q-and-a.md](../../ja/q-and-a.md) のQ6にあるEmacs風キーバインドを、**GUIを操作せずに**、リポジトリ管理された設定ファイルからMozcへ適用すること。

> 注意: このメモはソースコードを読んで得た知見であり、実機（macOS）ではまだ検証していない。「要検証」と書いた箇所は特に注意する。

## 結論

- Mozcの設定は `config1.db` という1ファイルに集約されている。中身は `mozc.config.Config`（`src/protocol/config.proto`）を**そのままシリアライズしたprotobufバイナリ**で、暗号化や難読化はない。
- `protoc --encode` を使えば、テキスト形式（textproto）からバイナリを生成できる。**GUIは不要**。この手順は公式ドキュメント `docs/configurations.md` にも書かれている。
- キーマップは `session_keymap: CUSTOM` と `custom_keymap_table`（TSV文字列）で指定する。
- CUSTOMを指定すると組み込みキーマップは**読み込まれず、全体が置き換わる**。そのため、`kotoeri.tsv`（macOSの既定）をベースに差分を追記したTSVを作るのがよい。
- 同じ状態・同じキーの定義が複数ある場合は**後に書いた行が勝つ**ため、ベースへの追記で上書きできる。
- 適用するには、ファイルを置き換えた後に変換サーバープロセスを再起動する。

```
keymap.tsv (管理対象)        config.textproto (管理対象)
        \                        /
         +--> 生成スクリプト --> config.textproto(完成形)
                                     |
                         protoc --encode=mozc.config.Config
                                     v
              ~/Library/Application Support/<製品>/config1.db
                                     |
                       killall <Converterプロセス>
```

## インストールについて（Google日本語入力とMozcのどちらを使うか）

macOSで使える選択肢は2つある。

| 選択肢 | 入手方法 | 設定ディレクトリ | 変換プロセス |
| --- | --- | --- | --- |
| Google日本語入力 | `brew install --cask google-japanese-ime`（調査時点の版は 3.34.6260） | `~/Library/Application Support/Google/JapaneseInput/` | `GoogleJapaneseInputConverter`（要検証） |
| Mozc（OSS版） | 自前でビルド（`bazelisk build package --config release_build`）、またはGitHub Actionsの成果物 `Mozc.pkg` | `~/Library/Application Support/Mozc/` | `MozcConverter` |

ディレクトリの切り替えは `src/base/system_util.cc` で行われている（`GOOGLE_JAPANESE_INPUT_BUILD` の場合は `Google/JapaneseInput`、それ以外は `Mozc`）。プロセス名 `MozcConverter` は `src/mac/installer/postflight_template.sh` の `killall MozcConverter` で確認した。

**当面はbrewでGoogle日本語入力を入れる方が現実的**だと判断した。

- Homebrewには公式Mozcのcaskがなく、OSS版を使うにはビルドするかCIの成果物を取得する必要がある。
- Google日本語入力はMozcと同じコードベースなので、`config1.db` の形式とキーマップの仕組みは共通である。
- proto2は未知のフィールドを無視するため、Mozc masterの `config.proto` でエンコードしたファイルも基本的には読める。ただし、新しく追加されたフィールドは効かない可能性がある。
- WindowsでもGoogle日本語入力を使う構成（q-and-a.md Q8）と揃えられる。
- 一方、Linux（Fcitx5 + Mozc）はOSS版になる。キーマップのTSVはどちらでも共通の形式である。

## 設定ファイルの仕様

### config1.db

- パス: `<ユーザープロファイルディレクトリ>/config1.db`。ファイル名の `1` は `config_version` に対応する（`src/config/config_handler.cc`）。
- 読み込み処理: `ConfigHandlerImpl::Reload()` が `ParseFromIstream` で読み込む。壊れたファイルの場合は**エラーにならず、デフォルト設定に戻る**。
- ファイルが存在しなければデフォルト設定で動作する。GUIで一度も保存していなければ、ファイルは存在しない可能性がある。
- 書き込みは `SetConfig()`（GUIからIPC経由）で行われる。そのため、GUIの設定画面で「OK」を押すと、手で置いたファイルは**上書きされる**。

キーマップに関係するフィールドは以下の通り（`src/protocol/config.proto`）。

```proto
enum SessionKeymap {
  NONE = -1;  // KOTOERI(mac) / MSIME(win) に置き換えられる
  CUSTOM = 0;
  ATOK = 1;
  MSIME = 2;
  KOTOERI = 3;
  MOBILE = 4;
  CHROMEOS = 5;
  OVERLAY_HENKAN_MUHENKAN_TO_IME_ON_OFF = 100;
}
optional SessionKeymap session_keymap = 41 [default = NONE];
optional bytes custom_keymap_table = 42;          // TSV文字列
repeated SessionKeymap overlay_keymaps = 68 [packed = true];
```

`overlay_keymaps` で重ねられるのは組み込みのキーマップファイルだけである。独自の差分を重ねる用途には使えない。

### custom_keymap_table（TSV）

読み込み処理は `src/session/keymap.cc` の `LoadStreamWithErrors` で、仕様は次の通り。

- **1行目は無条件に読み飛ばされる**（ヘッダー `status\tkey\tcommand`）。ヘッダーを書き忘れると、最初のルールが無視される。
- 空行と `#` で始まる行は無視される。
- 各行はタブ区切りの3列 `状態 キー コマンド` で書く。列数が3でない行はログに出力されたうえで無視される。
- 同じ状態・同じキーの定義は `flat_hash_map` に代入されるため、**後の行が勝つ**。
- 定義を削除する構文はない。外したいキーは、ベースのTSVからその行を取り除く必要がある。

状態名には `DirectInput`（`Direct` でも可）、`Precomposition`、`Composition`、`Conversion`、`Suggestion`、`Prediction`、`ZeroQuerySuggestion` がある。

- `Suggestion` に定義がないキーは `Composition` の定義が使われる。
- `Prediction` に定義がないキーは `Conversion` の定義が使われる。

キー名の書式は `Ctrl Shift f` のように、修飾キーとキーを空白で区切って並べる。大文字小文字は区別されない（`src/composer/key_parser.cc`）。

- 修飾キー: `Ctrl` / `Alt`（=`Option`）/ `Shift` / `Meta` / `Super` / `Hyper` / `Caps` など
- 特殊キー: `Enter` `Space` `Tab` `ESC` `Backspace` `Delete` `Left` `Right` `Up` `Down` `Home` `End` `PageUp` `PageDown` `Henkan` `Muhenkan` `Kana` `Eisu` `Hankaku/Zenkaku` `F1`〜 など

利用できるコマンドの一覧は `src/session/keymap.cc` の `InitCommandData()` にある。各組み込みTSVで使われているコマンドは以下の通り。

```
Backspace Cancel CancelAndIMEOff Commit CommitFirstSuggestion CommitOnlyFirstSegment
CompositionModeFullKatakana CompositionModeHiragana CompositionModeSwitchKanaType
Convert ConvertNext ConvertNextPage ConvertPrev ConvertPrevPage
ConvertToFullAlphanumeric ConvertToFullKatakana ConvertToHalfAlphanumeric
ConvertToHalfWidth ConvertToHiragana ConvertWithoutHistory Delete
DeleteSelectedCandidate DisplayAsFullAlphanumeric DisplayAsFullKatakana
DisplayAsHalfAlphanumeric DisplayAsHalfWidth DisplayAsHiragana IMEOff IMEOn
InsertAlternateSpace InsertCharacter InsertFullSpace InsertHalfSpace InsertSpace
LaunchConfigDialog LaunchWordRegisterDialog MoveCursorLeft MoveCursorRight
MoveCursorToBeginning MoveCursorToEnd PredictAndConvert Reconvert Revert
SegmentFocusFirst SegmentFocusLast SegmentFocusLeft SegmentFocusRight
SegmentWidthExpand SegmentWidthShrink SwitchKanaType ToggleAlphanumericMode Undo
```

## キーがIMEとアプリのどちらに渡るか（q-and-a.md Q7との関係）

`src/session/session.cc` と `src/mac/mozc_imk_input_controller.mm` を読むと、未定義のキーの扱いは状態によって次のように異なる。

| 状態 | キーマップに定義がないキー | 結果 |
| --- | --- | --- |
| Direct | 送られない（IMEオンにするキー以外） | アプリが処理する |
| Precomposition | `EchoBackAndClearUndoContext`（consumed=false） | **アプリが処理する** |
| Composition / Suggestion | `DoNothing`（consumed=true） | IMEが握りつぶす |
| Conversion / Prediction | `DoNothing`（consumed=true） | IMEが握りつぶす |

macOS側では、`handleEvent:` が `output.consumed()` をそのまま返している。consumedがfalseであれば、キーはアプリ（Cocoaのテキスト入力系）に渡る。

つまり、**Precompositionに `Ctrl n` などを定義しなければ**、IMEがオンでも未入力の状態ではアプリ側のEmacsキーバインドが効く。これはQ7の要求とそのまま一致する。kotoeri.tsvでPrecompositionに定義されているCtrl系のキーは `Ctrl Backspace`（Undo）と `Ctrl Shift r`（Reconvert）だけである。

また、読みの入力中や変換中に未定義のCtrlキーを押した場合は、アプリに渡らずIMEに消費される。そのため、変換中に誤ってアプリのショートカットが発動することはない。

## 既定のkotoeri.tsvとQ6の差分

macOSの既定キーマップ（kotoeri.tsv）には、もともとEmacs風の定義が多く含まれている。

Composition（読みの入力中）:

| キー | kotoeri | Q3の要求 |
| --- | --- | --- |
| `Ctrl a` / `Ctrl e` | 先頭へ / 末尾へ | 一致 |
| `Ctrl b` / `Ctrl f` | 1文字左へ / 1文字右へ | 一致 |
| `Ctrl d` / `Ctrl h` | Delete / Backspace | 一致 |
| `Ctrl g` | Cancel | 一致 |
| `Ctrl m` | Commit | 一致 |
| `Ctrl n` / `Ctrl p` | Compositionでは未定義、Suggestion中の `Ctrl n` は PredictAndConvert | ほぼ一致 |

Conversion（変換中）:

| キー | kotoeri | Q3/Q6の要求 | 対応 |
| --- | --- | --- | --- |
| `Ctrl b` / `Ctrl f` | SegmentFocusLeft / Right | 前後の文節へ | 一致 |
| `Ctrl n` / `Ctrl p` | ConvertNext / ConvertPrev | 次候補 / 前候補 | 一致 |
| `Ctrl a` | SegmentFocusFirst | 最初の文節へ | 一致 |
| `Ctrl e` | **ConvertPrev** | 最後の文節へ | **上書きする** |
| `Ctrl g` | **未定義** | Cancel | **追加する** |
| `Ctrl m` | Commit | 確定 | 一致 |
| `Ctrl i` / `Ctrl o` | SegmentWidthShrink / Expand | — | 既存のまま |
| `Shift Left` / `Shift Right` | SegmentWidthShrink / Expand | — | 既存のまま |
| `Ctrl Shift b` / `Ctrl Shift f` | 未定義 | 文節を縮める / 伸ばす | **追加する** |

Ctrl+Shift+文字キーについて: `src/mac/KeyCodeMap.mm` のコメントによれば、macOSでは `\C-S-a` は「CTRL + SHIFT + a」（小文字）としてMozcに渡される。したがって、TSVには `Ctrl Shift b` と書けばよい（要検証）。

`Ctrl i` とTabが区別できるかについて: macOSでは `charactersIgnoringModifiers` からキーを取得するため、`Ctrl i` は Tab ではなく `Ctrl` + `i` になると読める。Linux（Fcitx5）では別途確認が必要である。

差分として追記するTSVは次の通り。

```tsv
# --- emacs overrides (後に書いた行が勝つ) ---
Conversion	Ctrl e	SegmentFocusLast
Conversion	Ctrl g	Cancel
Conversion	Ctrl Shift b	SegmentWidthShrink
Conversion	Ctrl Shift f	SegmentWidthExpand
```

## GUIを使わない適用手順（案）

### 準備

```sh
brew install protobuf   # protoc
# config.proto は import のない単独ファイルなので、1ファイルだけ取得すればよい
curl -fsSLO https://raw.githubusercontent.com/google/mozc/master/src/protocol/config.proto
curl -fsSLO https://raw.githubusercontent.com/google/mozc/master/src/data/keymap/kotoeri.tsv
```

### 管理するファイル

- `keymap.overrides.tsv`: 上記の差分。ヘッダーは不要で、生成時に連結する。
- `config.base.textproto`: キーマップ以外の設定（ローマ字/かな、句読点など）。最初は既存の `config1.db` をデコードして作るとよい。

```sh
DB="$HOME/Library/Application Support/Google/JapaneseInput/config1.db"   # OSS版なら .../Mozc/config1.db
protoc --decode=mozc.config.Config config.proto < "$DB" > config.base.textproto
```

`general_config`（`last_modified_time` など）や既存の `session_keymap` / `custom_keymap_table` は、base側から削除しておく。

### 生成と適用

```sh
#!/bin/sh
set -eu
DIR="$HOME/Library/Application Support/Google/JapaneseInput"
# DIR="$HOME/Library/Application Support/Mozc"

# 1. キーマップTSV = kotoeri.tsv（ヘッダー行を含む） + 差分
cat kotoeri.tsv keymap.overrides.tsv > keymap.tsv

# 2. textprotoを組み立てる（TSVはエスケープした文字列としてbytesフィールドに埋め込む）
{
  cat config.base.textproto
  echo 'session_keymap: CUSTOM'
  printf 'custom_keymap_table: "%s"\n' "$(python3 -c 'import sys;s=open(sys.argv[1]).read();print(s.replace("\\","\\\\").replace("\"","\\\"").replace("\t","\\t").replace("\n","\\n"),end="")' keymap.tsv)"
} > config.textproto

# 3. バイナリにエンコードし、デコードして中身を確認する
protoc --encode=mozc.config.Config config.proto < config.textproto > config1.db
protoc --decode=mozc.config.Config config.proto < config1.db | head

# 4. バックアップを取ってから置き換える
[ -f "$DIR/config1.db" ] && cp "$DIR/config1.db" "$DIR/config1.db.bak.$(date +%s)"
cp config1.db "$DIR/config1.db"

# 5. 変換サーバーを再起動する（次のキー入力時に自動で再起動される想定）
killall GoogleJapaneseInputConverter 2>/dev/null || killall MozcConverter 2>/dev/null || true
```

補足:

- サーバーは起動時に `config1.db` を読み込む。`RELOAD` コマンドはエンジン（辞書）を再読み込みするだけで、`ConfigHandler::Reload()` は呼ばない。そのため、ファイルを置き換えた後はプロセスの再起動が必要になる。
- macOSのクライアント（`Mozc.app` / IMKコントローラー）は、入力モードを切り替えるときなどに `GetConfig` でサーバーから設定を取得する。キーマップの解釈はサーバー側で行われるので、サーバーを再起動すれば反映される見込み（要検証）。
- 壊れたファイルを置いた場合は、エラーにならずデフォルト設定に戻る。キーマップが効かないときは、まずデコードして中身を確認する。

## 未検証・今後確認すること

- [ ] Google日本語入力（brew版）で、上記パスの `config1.db` の差し替えとプロセスの再起動だけで反映されるか
- [ ] Google日本語入力の変換プロセスの実際の名前（`pgrep -fl JapaneseInput` で確認する）
- [ ] `Ctrl Shift b/f` がmacOSで期待通りに届くか
- [ ] Precompositionの `Ctrl n` が、Cocoaアプリ（TextEdit、ブラウザーのテキストエリアなど）で次行移動になるか
- [ ] Composition中の `Ctrl n`（サジェストなし）はIMEに消費されて何も起きない。これを `Convert` などに割り当てるかどうか
- [ ] TSVのうち、OS共通にできる部分と、OSごとの差分（Fcitx5でのCtrl+Shiftの扱いなど）の切り分け
- [ ] GUIで保存すると上書きされる問題への対策（GUIを使わないという運用でよいか）

## 参照したソース

- `docs/configurations.md`: config1.dbのprotoc encode/decodeの手順
- `src/protocol/config.proto`: `Config` メッセージ
- `src/config/config_handler.cc`: 読み込み・保存とファイル名
- `src/base/system_util.cc`: ユーザープロファイルディレクトリ
- `src/session/keymap.cc` / `keymap.h`: TSVの読み込み、上書きの規則、コマンド一覧
- `src/session/session.cc`: 未定義のキーが消費されるかどうか
- `src/composer/key_parser.cc`: キー名
- `src/mac/mozc_imk_input_controller.mm` / `KeyCodeMap.mm`: macOSのキーイベント処理
- `src/data/keymap/kotoeri.tsv`: macOSの既定キーマップ
- `src/mac/installer/`: プロセス名、LaunchAgent
