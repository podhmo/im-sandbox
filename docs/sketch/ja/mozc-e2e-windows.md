# Windows での Mozc (Google日本語入力) 設定適用と E2E 調査メモ

調査日: 2026-11-16（検証追記: 同日。Google日本語入力 3.34.6260.0 で E2E 実施・全件PASS）
対象: Windows 上の Google日本語入力（調査時点の最新は 3.34.6260 系、2026-08 リリース）
関連: [mozc-e2e-mac.md](./mozc-e2e-mac.md), [mozc-wslg-setup.md](./mozc-wslg-setup.md), [mozc-e2e-linux.md](./mozc-e2e-linux.md), [mozc-customization.md](./mozc-customization.md)

macOS / WSLg と同じく、「リポジトリ管理の `mozc/keymap.tsv` + `config.base.textproto` から `config1.db` を生成して適用し、E2E でカスタムキーマップの動作を確認する」ことを Windows で実現した。`mozc/*.ps1` と `tools/mozc_e2e_win.cs` として実装済みで、`mozc/e2e.ps1 custom` が **14/14 PASS** することを確認済み。

## 対象となる構成

q-and-a.md Q8 の方針どおり、Windows では **Google日本語入力** を使う。Mozc と同じコードベースなので `config1.db` の形式とキーマップ TSV の仕組みは共通のはず。

```
キー入力 → Windows → TSF (Text Services Framework)
                    → Google日本語入力 TIP (mozc_tip64.dll)
                    → 変換サーバー GoogleIMEJaConverter.exe (config1.db を読むのはここ)
                    → 候補表示 GoogleIMEJaRenderer.exe
```

Linux の `fcitx5 → mozc_server` と同じ2層構造で、`mozc_server` に相当するのが `GoogleIMEJaConverter.exe`。

## 調べてわかったこと

### 設定ディレクトリとプロセス

ソース根拠: `src/base/system_util.cc` の `GetUserProfileDirectory()` は `_WIN32` では `WinUtil::GetLocalAppDataPath()`（→ `base/win32/win_util.cc` で `FOLDERID_LocalAppDataLow`）に、`GOOGLE_JAPANESE_INPUT_BUILD` のときは `kCompanyNameInEnglish`（Google）、続いて `kProductNameInEnglish`（Google Japanese Input）を連結する。

|| macOS | Linux | Windows |
|---|---|---|---|
| 設定ディレクトリ | `~/Library/Application Support/Google/JapaneseInput` | `~/.config/mozc` | **`%USERPROFILE%\AppData\LocalLow\Google\Google Japanese Input`** |
| OSS版 (Mozc) | `~/Library/Application Support/Mozc` | （同上） | `%USERPROFILE%\AppData\LocalLow\Mozc` |
| 変換プロセス | `GoogleJapaneseInputConverter` | `mozc_server` | **`GoogleIMEJaConverter.exe`** |
| インストール先 | `/Library/Input Methods/GoogleJapaneseInput.app` | `/usr/lib/mozc` | `C:\Program Files (x86)\Google\Google Japanese Input` |

- 学習ファイルは `segment.db` `boundary.db` `cform.db` `history.db` `encrypt_key.db`（実機で確認）。**mac/Linux の `.history.db`/`.encrypt_key.db` とは違い、Windows では先頭ドットが付かない**ので退避リストは `history.db` を使う。`encrypt_key.db` は履歴復号の鍵なので退避・消去の対象外。`config1.db` は macOS で生成したものと同一フォーマットで使い回せることを実機で確認した（このリポジトリで生成した config1.db をそのまま適用して動作した）。
- `GoogleIMEJaConverter.exe` を止めても、次に IME が使われた時点で自動再起動する（macOS の MachServices オンデマンド起動と同じ）。つまり適用手順は macOS 版と同じ「ファイルを置き換えてから変換プロセスを kill」でよい。
- ほかの GoogleIMEJa* プロセス: `GoogleIMEJaRenderer.exe`（候補ウィンドウ描画）、`GoogleIMEJaCacheService.exe`、`GoogleIMEJaTool.exe`（設定GUI。開くと config1.db 上書きの危険 = article.html C11 と同じ問題）。

### TIP の識別子（入力メソッドの切り替えに使う）

| | CLSID (TextService) | Profile GUID | langid |
|---|---|---|---|
| Google日本語入力 | `{D5A86FD5-5308-47EA-AD16-9C4EB160EC3C}` | `{773EB24E-CA1D-4B1B-B420-FA985BB0B80D}` | `0x0411` |
| OSS Mozc | `{10A67BC8-22FA-4A59-90DC-2546652C56BF}` | `{186F700C-71CF-43FE-A00E-AACB1D9E6D3D}` | `0x0411` |

出典: mozc `src/base/system_util.cc`（CLSID）と mozc `src/win32/base/imm_util.cc`・Firefox `TSFStaticSink.cpp`（profile GUID）。

プログラムからの切り替えは2系統ある（`src/win32/base/imm_util.cc` `ImeUtil::SetDefault()` が両方やっている）:

1. `InstallLayoutOrTip("0x0411:{CLSID}{profileGUID}")` + `SetDefaultLayoutOrTip`（input.dll の API。PowerShell からも P/Invoke で呼べる）
2. `ITfInputProcessorProfileMgr::ActivateProfile(TF_PROFILETYPE_INPUTPROCESSOR, 0x0411, clsid, profileGuid, ...)`（TSF の正式 API）

手動では「設定 → 時刻と言語 → 言語と地域 → 日本語 → キーボード」で追加、または `Win+Space` で選択。

**検証結果**: このマシンでは `Get-WinUserLanguageList` の先頭（=既定 TIP）がすでに Google日本語入力だったため、プロファイル切り替えは不要だった。試した限りでは C# の `ComImport` 経由の `ActivateProfile` は `E_NOINTERFACE` を返し、`InstallLayoutOrTip` も `False` を返した（インターフェース宣言の問題の可能性。E2E には不要なので深追いしていない）。

### 既定キーマップの差

`session_keymap: NONE` は macOS では KOTOERI、**Windows では MSIME** に解決される（`config.proto` のコメント）。したがって:

- カスタムキーマップ（`CUSTOM` + `custom_keymap_table`）はそのまま使える。
- E2E のネガティブコントロールは、macOS の `kotoeri` に相当するものとして **`session_keymap: MSIME`** を使う（`default` モードに相当）。
- `src/data/keymap/ms-ime.tsv` を見ると、Windows 版でも `Hankaku/Zenkaku`（半角/全角キー）が `DirectInput` で `IMEOn` に割り当てられており、TSV のキー名は OS 共通で通用する。**ただし US 配列キーボードには半角/全角キーが物理的に存在しない**ので注意（後述）。

## E2E の方式

| 方式 | macOS | Linux (WSLg) | Windows |
|---|---|---|---|
| A. エンジン単体（`session_handler_main` + シナリオファイル） | 未採用（将来の選択肢） | 同上 | 同上。**OS 共通で使い回せる点は全 OS で同じ**。Windows でのビルドは bazel + MSVC で重い |
| B. 実機E2E（キー注入 + 実エディタのテキスト読取） | CGEvent + TextEdit | xdotool/XTEST + gedit・probe | **SendInput + メモ帳 or 自作プローブ**。採用候補 |
| C. IM直接呼び出し（決定的） | — | D-Bus 仮想IC (`org.fcitx.Fcitx.InputMethod1`) | **直接対応するものが無い**。mozc の Windows IPC は named pipe で、クライアントを自作する必要がある。将来は A と同じ |

**B を採用し、`tools/mozc_e2e_win.cs` として実装済み**。macOS 版と同じ構造。要素の対応は次の通り:

| 要素 | macOS (`mozc_e2e_mac.swift`) | Windows 版（実装済み） |
|---|---|---|
| キー注入 | `CGEvent.post(.cghidEventTap)`、物理キーコード + 修飾フラグ | **`SendInput`**（Win32）。VK コード + 修飾キー（Ctrl/Shift は修飾キー自体を INPUT で送る方式）。**権限は不要**（アクセシビリティ権限のような前準備が無いのは macOS より楽） |
| 権限 | 実行元アプリのアクセシビリティ権限が必須 | 基本不要。ただし **UIPI** で、非昇格プロセスから昇格ウィンドウにはキーを送れない → ランナーは非昇格で実行 |
| IME 切り替え | `TISSelectInputSource` | 不要（ja-JP の既定 TIP が Google日本語入力。`Get-WinUserLanguageList` の先頭） |
| IME を ひらがな（入力オン）にする | `com.google.inputmethod.Japanese.base` を選ぶだけ | **IMM32 `ImmSetOpenStatus(true)` + `ImmSetConversionStatus(IME_CMODE_NATIVE\|IME_CMODE_FULLSHAPE)` を WPF ウィンドウの HIMC に対して実行**（ケースごとに呼ぶ） |
| テキスト取得 | AppleScript で TextEdit の `text of document 1` | **自作 WPF TextBox プローブ**（`mozc_e2e_win.cs` 内に同居）。`PreviewKeyDown` でアプリに転送されたキーも記録し、IME が消費したかの判定に使う |

ランナーは `.NET Framework 同梱の csc.exe`（`C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe` + WPF アセンブリ参照）で単一 `.cs` を都度コンパイルする形。ツール導入ゼロ。`e2e.ps1` が存在しなければ自動でコンパイルする。

### Windows 実装でハマった点（記録）

- **`SendInput` の `INPUT` 構造体は x64 で 40 バイト必要**。union なので `type`(4B)+padding(4B) のあと offset 8 に `KEYBDINPUT` を置く。32 バイトで宣言すると全注入が `SendInput failed` になる（最初ここで全滅した）。
- **WPF `TextBox.Text` は確定テキストだけでなく preedit（変換中の表示文字列）も含む**。`CommitOnlyFirstSegment` の「先頭文節だけ確定」を `mid != got` で判定しようとして失敗した。対策: `C-S-m` の後に `Ctrl g` を送り、変換が続いていれば IME が消費、全確定済みなら precomposition としてアプリに転送され keylog に「Ctrl g」が残る、という振る舞いベースの判定に変えた（読みは先頭文節が漢字になる `kanjiwokaku` に変更して結果も区別）。
- IME に処理されたキーは WPF の `PreviewKeyDown` に `Key.ImeProcessed` として届く（keylog では `?` と表示）。本当にアプリへ転送されたキーだけ実キー名が出るので、消費/転送の判別に使える。
- 修飾キー単体の down も PreviewKeyDown に来る（`Ctrl` `Shift`）ので keylog では除外している。

## 作ったもの（macOS/Linux との対応・実装済み）

| 既存 | Windows 版 | 内容 |
|---|---|---|
| `mozc/build.sh` | `mozc/build.ps1` | keymap.tsv を textproto に埋め込み `protoc --encode`。Python 依存は PowerShell の文字列置換で代替（python3 不要）。`config.proto` は `mozc/third_party/mozc/protocol/` に配置 |
| `mozc/apply.sh linux/google` | `mozc/apply.ps1` | `out/config1.db` → `%USERPROFILE%\AppData\LocalLow\Google\Google Japanese Input\config1.db` へコピー（`.bak.<timestamp>` 退避付き）→ converter を `Get-Process \| Stop-Process` で停止（`taskkill` は process-not-found が PowerShell の $ErrorActionPreference=Stop でエラー化するので避けた） |
| `mozc/clear-learning.sh` | `mozc/clear-learning.ps1` | 同じ学習ファイルを `out/learning-backup-*` へ退避。サーバー停止→退避→再停止の流れも同じ |
| `mozc/e2e.sh` | `mozc/e2e.ps1` | NO_HISTORY 付き textproto → encode → コンバーター停止 → `config1.db` 差し替え + 学習ファイル退避 → ランナー実行 → `finally` で必ず復元。`custom`/`default`(=MSIME) の2モード、`--only <文字列>` でケース絞り込み可 |
| `tools/mozc_e2e_mac.swift` / `mozc_e2e_fcitx5.py` / `mozc_e2e_gui.py` | `tools/mozc_e2e_win.cs` | 上記B方式。WPF TextBox プローブ内蔵。CASES は Linux 版を移植（14件） |
| （プローブ） | `tools/probe_ime_on.cs` | IMM32 での IME オンだけを試す最小 repro。ランナーが効かないときの切り分け用 |

依存の導入（ユーザーが実施）:

- **Google日本語入力**: 3.34.6260.0 をインストール済み。
- **protoc**: `winget install Google.Protobuf`（36.2）でインストール済み。
- **mozc ソース**: `config.proto` だけを GitHub から取得し `mozc/third_party/mozc/protocol/` に配置（import 無しの単独ファイル）。git 不要。
- Python 不使用。`csc.exe` は .NET Framework 同梱。

## 実機検証結果（2026-11-16, Google日本語入力 3.34.6260.0）

`powershell -ExecutionPolicy Bypass -File .\mozc\e2e.ps1 custom` の結果:

```
PASS  composition: C-g でキャンセル
PASS  composition: C-b / C-d / C-a / C-e / C-h
PASS  composition: C-n で変換に進む (PredictAndConvert)
PASS  conversion: C-g で変換キャンセル
PASS  conversion: C-o で文節を伸ばす
PASS  conversion: C-i で縮める + C-e / C-a で文節移動
PASS  conversion: C-f / C-b で文節移動
PASS  conversion: C-S-b / C-S-f でも文節を伸縮
PASS  conversion: Tab も文節を縮める
PASS  conversion: C-S-m で先頭の文節だけ確定
PASS  conversion: Shift Enter も先頭の文節だけ確定
PASS  conversion: C-n → C-p で元の候補に戻る
PASS  precomposition: C-p / C-a はアプリに渡る
PASS  directinput: 半角/全角キーで IME オン/オフ

14/14 passed
```

## Windows 固有の注意点（検証済みの結果を併記）

1. **Ctrl+Shift による入力言語切り替えホットキーと衝突する**。Windows には「入力言語のホットキー」（既定で Ctrl+Shift や左 Alt+Shift が IME/言語切り替えに割当）があり、`C-S-b/f` `C-S-v` `C-S-m` `C-S-d` `C-S-Space` とぶつかる。対策: 「設定 → 時刻と言語 → 入力 → 詳細なキーボード設定 → 入力言語のホットキー」で「キーシーケンス」を未割り当てにする。Google日本語入力のインストーラー初回画面にも「Ctrl+Shift による切り替えを無効化」の選択肢がある。**検証**: この環境では言語が ja 1つのみで切り替え先が無く、無効化しなくても `C-S-b/f/m` が素通りせず Mozc に届いた。複数言語がある環境では依然として注意が必要。
2. **`C-i`/Tab、`C-m`/Enter、`C-h`/Backspace は Windows では区別できる**（検証済み）。VK コードで届くので X11 のような keysym 正規化が起きない。`Tab` ケースと `C-i` ケースが別々に PASS した。
3. **`Ctrl+Shift+文字` も Shift が保持されて届く**（検証済み）。Linux/X11 の `Ctrl+Shift+m → Ctrl+m` 正規化問題は発生しない。`C-S-b/f`（文節伸縮）と `C-S-m`（先頭文節のみ確定）が PASS。
4. **半角/全角キー（VK 0xF3）は SendInput で注入でき、`Hankaku/Zenkaku` として認識される**（検証済み。directinput ケースが PASS）。物理キーが無い US 配列でも注入は機能するはずだが、運用キーとしては US 配列だと押せないので別キー（無変換/変換も US 配列には無い）の追加を検討する余地あり。
5. **Windows 側ショートカットに取られるキー**は WSLg と同様に注意。Win+* 系、`Ctrl+Alt+Del` 系、`Alt+Tab` は OS が先に取る。`Ctrl+*` 単体は今回のケース全て IME/アプリに届いた。
6. **GUI の設定ツールを開いて「OK」を押すと config1.db が上書きされる**（article.html C11 と同じ問題。Windows 版の設定ツールは `GoogleIMEJaTool.exe` / 通知領域の「プロパティ」）。
7. **メモ帳は状態を復元する**ので E2E には自作 WPF TextBox プローブを採用した（再起動してもクリーン、`PreviewKeyDown` で転送キーも記録できる）。
8. **非隔離実行の副産物**: e2e.ps1 を介さずにランナーを直接実行したとき、確定結果が学習されて以後の候補順が変わった（「ここではきものをぬグ」が最上位候補に出るようになった）→ **必ず `e2e.ps1`（NO_HISTORY + 学習ファイル退避）経由で実行すること**。汚染が気になる場合は `clear-learning.ps1` で退避できる。

## 使い方

```powershell
# 1回だけの初期化: config.proto を配置（build.ps1 が参照）
#   mozc/third_party/mozc/protocol/config.proto

# 設定の生成と適用
powershell -ExecutionPolicy Bypass -File .\mozc\build.ps1
powershell -ExecutionPolicy Bypass -File .\mozc\apply.ps1

# E2E（NO_HISTORY・学習退避つき。終了時に config1.db と学習ファイルを復元）
powershell -ExecutionPolicy Bypass -File .\mozc\e2e.ps1 custom          # カスタムキーマップ（期待: 14/14 PASS）
powershell -ExecutionPolicy Bypass -File .\mozc\e2e.ps1 custom --only "先頭"  # ケース絞り込み
powershell -ExecutionPolicy Bypass -File .\mozc\e2e.ps1 default         # MSIME 既定キーマップ（ネガティブコントロール）

# 学習データの消去（退避）
powershell -ExecutionPolicy Bypass -File .\mozc\clear-learning.ps1
```

## 未検証・今後

- [x] Google日本語入力（Windows版）で `custom_keymap_table` がそのまま効くか → **効く**（14/14 PASS）
- [x] 半角/全角キーの SendInput 注入が `Hankaku/Zenkaku` として認識されるか → **認識される**（VK 0xF3）
- [x] 「入力文字なしの Ctrl キーがアプリに渡る」セマンティクス → **渡る**（precomposition ケース PASS）
- [x] Ctrl+Shift+文字 → **Shift 保持で届く**（この環境では言語切り替えホットキー無効化も不要だった）
- [x] `e2e.ps1 default`（MSIME キーマップ）で差分が検出されるか → **検出される**（3/14 のみ PASS。C-g でキャンセルされず `あいうえ` が残る、C-o 系で `ｺｺﾃﾊ` になるなど、カスタムキーマップとの差分が明確。PASS した3件は MSIME でも同じ結果になるケース）
- [ ] `ITfInputProcessorProfileMgr::ActivateProfile` / `InstallLayoutOrTip` でのプロファイル有効化（今回は不要だった。複数 TIP 環境で必要になったら再調査）
- [ ] US 配列での IME オン/オフの運用キー
- [ ] `Ctrl+Shift` 言語切り替えが実際に有効な環境（複数言語インストール済み）での再検証
- [ ] CI/無人実行は macOS 版と同じく GUI セッションが必要。無人化するなら A 方式（`session_handler_main`）
