# Mozcキーマップの動作確認を自動化する（macOS版の模索）

調査日: 2026-11-13
対象: Google日本語入力 3.34.6260（brew cask）、macOS 15.8.1
関連: [mozc-customization.md](./mozc-customization.md)

## 目的

[mozc-customization.md](./mozc-customization.md) で適用したEmacs風キーマップが、実際に期待通りに動くかを手で確認するのは面倒である。そのため、確認作業を自動化したい。

## 方式の候補

| 方式 | 何を検証できるか | コスト |
| --- | --- | --- |
| A. エンジン単体のシナリオテスト（Mozcの `session_handler_main`） | キーマップの意味（どのキーでどのコマンドが実行されるか）。OSに依存せず再現性が高い | Mozcのビルドが必要。この環境にはXcodeがないため、Linux向けにDockerでビルドすることになる |
| B. 実機E2E（CGEventでキーを送り、TextEditの内容を読む） | OSのキー変換、IMEとアプリの間のキーの受け渡し、実際の変換結果 | macOS専用。アクセシビリティ権限が必要。変換の学習で結果が揺れる |

**今回はBを採用した**。フルビルドはまだ避けたいためである。

Aは将来の選択肢として残す。メモしておくと次の通り。

- `src/session/session_handler_main.cc` には `--profile`（ユーザープロファイルディレクトリ）と `--test` フラグがある。
- シナリオファイルには `SEND_KEYS` / `SEND_KEY` / `EXPECT_PREEDIT_IN_DETAIL` などを書ける。例は `src/data/test/session/scenario/` にあり、`segment_width.txt` などが参考になる。
- 自前の `config1.db` を置いたディレクトリを `--profile` に指定すれば、同じキーマップで検証できる見込みである。
- WSLgやLinuxでも同じシナリオを使い回せる点が魅力である。

## B. 実機E2Eの仕組み

スクリプト: [`tools/mozc_e2e_mac.swift`](../../../tools/mozc_e2e_mac.swift)

```
swift tools/mozc_e2e_mac.swift            # 全ケースを実行
swift tools/mozc_e2e_mac.swift --only C-g # 名前の一部で絞り込む
```

実行方法: **iTerm2のタブで `swift` コマンドをそのまま実行する**（iTerm2にアクセシビリティ権限を付ける）。Claude Code（`!` を含む）やherdrの配下からは、権限が引き継がれないため動かない（詳細は後述）。

処理の流れ:

1. `TISSelectInputSource` で入力ソースを「ひらがな (Google)」（`com.google.inputmethod.Japanese.base`）に切り替える。
2. AppleScriptでTextEditの新規書類を作り、最前面にする。
3. `CGEvent` でキーイベントを `cghidEventTap` に送る。キーは物理キーコード（`kVK_ANSI_*`）と修飾キーのフラグで表す。
4. AppleScriptで `text of document 1` を読み、期待値と比較する。
5. 最後に、実行前の入力ソースに戻す。

### 学習で結果が揺れないための工夫

漢字の変換結果は学習で変わるため、期待値には漢字を含めない。代わりに次のような手順で、変換候補によらず結果が決まるようにしている。

- 文節を伸ばしきって1文節にしてから `C-j`（DisplayAsHiragana）で確定すると、読みと同じひらがなになる。これで `C-S-f`（SegmentWidthExpand）が効いたことを確認できる。
- 1文節にした後で `C-S-b`（SegmentWidthShrink）を押すと、末尾の1文字が別の文節に分かれる。`C-e` で最後の文節へ移動して `C-k`（カタカナ）、`C-a` で最初の文節へ移動して `C-j`（ひらがな）にすると、結果は `ここではきものをぬグ` に決まる。これで縮小と文節移動をまとめて確認できる。
- `C-n` → `C-p` については、押さずに確定した場合と結果が一致するかで確認する。

### テストケース

| ケース | 確認すること |
| --- | --- |
| composition: `C-g` | 読みの入力中のキャンセル |
| composition: `C-b` `C-d` `C-a` `C-e` `C-h` | 読みの中でのカーソル移動と削除 |
| conversion: `C-g` | 変換のキャンセル（今回追加したキー） |
| conversion: `C-S-f` | 文節を伸ばす（今回追加したキー） |
| conversion: `C-S-b` + `C-e` / `C-a` | 文節を縮める、最後の文節・最初の文節へ移動（今回追加・変更したキー） |
| conversion: `C-f` / `C-b` | 前後の文節へ移動 |
| conversion: `C-n` → `C-p` | 次候補と前候補が対になっていること |
| precomposition: `C-p` / `C-a` | IMEオン・未入力のときにキーがアプリへ渡ること（q-and-a.md Q7） |

## 実行結果（2026-11-13）

```
PASS  composition: C-g でキャンセル
PASS  composition: C-b / C-d / C-a / C-e / C-h
PASS  conversion: C-g で変換キャンセル
PASS  conversion: C-S-f で文節を伸ばす
PASS  conversion: C-S-b で縮める + C-e / C-a で文節移動
PASS  conversion: C-f / C-b で文節移動
PASS  conversion: C-n → C-p で元の候補に戻る
PASS  precomposition: C-p / C-a はアプリに渡る

8/8 passed (input source: com.google.inputmethod.Japanese.base, current: com.apple.keylayout.ABC)
```

既定のキーマップ（kotoeri）のままなら、次のケースは失敗するはずである。

- 変換中の `C-g` は既定では未定義なので、押しても何も起きず、そのまま確定すると漢字になる。
- `C-S-f` / `C-S-b` は既定では未定義なので、文節が変わらない。
- `C-e` は既定では「前の候補」（ConvertPrev）なので、最後の文節に移動しない。

追加・変更したキーのケースがPASSしたことは、カスタムキーマップが効いている根拠になる（逆に、既定のキーマップで実際に失敗することはまだ確認していない）。

## 分かったこと・ハマりどころ

- **アクセシビリティ権限が必要。** `CGEvent.post` でキーを送るには、実行元プロセスの「責任のあるアプリ」にアクセシビリティ権限が必要である。
  - Claude Code経由で実行する場合は、Claude Codeを動かしているターミナルアプリが対象になる。
  - 権限がないと、スクリプトは `AXIsProcessTrustedWithOptions` の確認で終了する。
  - この権限はそのアプリ上で動くすべてのプロセスにキー操作を許すことになるので、付与は慎重に判断する。
  - 設定する場所は「システム設定 → **プライバシーとセキュリティ** → アクセシビリティ」である。サイドバーにある「アクセシビリティ」（VoiceOverなどの補助機能の設定）とは別物なので注意する。
  - 「責任のあるプロセス」は、`responsibility_get_pid_responsible_for_pid` で確認できる。実際に確かめた結果は次の通り。
    - `swift script.swift` で実行すると、`swift-frontend`（`/Library/Developer/CommandLineTools/usr/bin/swift-frontend`）自身が責任のあるプロセスになる。
    - Claude CodeのBashツールや `!` から起動したプロセスは、コンパイル済みのバイナリであっても**自分自身**が責任のあるプロセスになった。親のherdrやiTerm2の権限は引き継がれない。herdrを許可しても効かなかった。
    - そのため、Claude Code経由で実行する場合は、`swiftc` でビルドした**固定パスのバイナリ自体**を許可する必要がある。
      - `swiftc -O tools/mozc_e2e_mac.swift -o mozc/out/mozc-e2e-mac`
      - ad-hocで署名されるため、TCC（macOSのプライバシー権限を管理する仕組み）は署名のハッシュでバイナリを識別していると思われる。その場合、**再ビルドするたびに許可し直しが必要**になる。
    - 素のiTerm2のタブ（マルチプレクサやClaude Codeの外）で実行する場合は、iTerm2に権限を付ければ動いた（確認済み）。**現時点ではこの方法をおすすめする。**
- **TISの一覧の取得方法で結果が変わる。** `TISCreateInputSourceList(filter, false)`（有効なものだけ）では、Google日本語入力が1件も返らないことがあった。`true`（インストール済みすべて）にすると取得できる。
- **入力モードのID:**

  | TIS ID | 表示名 |
  | --- | --- |
  | `com.google.inputmethod.Japanese.base` | ひらがな (Google) |
  | `com.google.inputmethod.Japanese.Roman` | 英数 (Google) |
  | `com.google.inputmethod.Japanese.Katakana` | カタカナ (Google) |
  | `com.google.inputmethod.Japanese.FullWidthRoman` | 全角英数 (Google) |
  | `com.google.inputmethod.Japanese.HalfWidthKana` | 半角カナ (Google) |

- **学習履歴への影響。** テストで確定した文字列は、ユーザーの学習履歴に入りうる。気になる場合は、テストの前後で設定の `incognito_mode` を切り替えることを検討する（未実装）。
- **TextEditの状態に依存する。** 自動修正や自動大文字化など、TextEdit側の設定で結果が変わる可能性がある。

## 未検証・今後

- [x] アクセシビリティ権限を付与したうえでの実行結果: 素のiTerm2タブで `swift tools/mozc_e2e_mac.swift` を実行し、**8/8 PASS**（2026-11-13）
- [x] キー間の待ち時間（現在40ms、変換後は200ms）: 今回の環境では十分だった
- [ ] `C-S-f` を12回押せば、どの読みでも1文節になるか（文節数が多いと足りない）
- [x] precompositionのケースで、TextEditの `C-p` / `C-a` が期待通りに動くか: PASS（IMEオン・未入力のときはアプリに渡る）
- [ ] （参考）Claude Code経由で実行する場合に、ビルドしたバイナリ（`mozc/out/mozc-e2e-mac`）を許可する方法が通るか。iTerm2から直接実行すれば足りるので、優先度は低い
- [ ] CIなどでの無人実行（GUIセッションが必要なので難しい）。無人で回したい場合はA方式を検討する
