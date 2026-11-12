// macOS 上の Google日本語入力 (Mozc) に実際のキーイベントを送り、TextEdit の内容で
// キーマップの動作を確認する E2E スクリプト。
//
// usage: swift tools/mozc_e2e_mac.swift [--source <TISInputSourceID>] [--only <case名の一部>]
//
// 前提:
//   - 実行するターミナル (または親アプリ) にアクセシビリティ権限があること
//     (システム設定 → プライバシーとセキュリティ → アクセシビリティ)
//   - 入力ソース「ひらがな (Google)」が追加済みであること
//   - 実行中は TextEdit が最前面になりキー入力を奪うので、操作しないこと
//
// 変換候補は学習で変わるため、期待値は「変換候補によらず決まる」形にしている
// (文節を伸縮したあと C-j/C-k でひらがな/カタカナ表示にして確定する、など)。
// テストで確定した文字列はユーザーの学習履歴に入りうる点に注意。

import AppKit
import Carbon
import Foundation

// MARK: - 引数

var sourceID = "com.google.inputmethod.Japanese.base"
var only: String? = nil
do {
  var it = CommandLine.arguments.dropFirst().makeIterator()
  while let a = it.next() {
    switch a {
    case "--source": sourceID = it.next() ?? sourceID
    case "--only": only = it.next()
    default:
      FileHandle.standardError.write("unknown arg: \(a)\n".data(using: .utf8)!)
      exit(2)
    }
  }
}

// MARK: - 入力ソース

func inputSource(_ id: String) -> TISInputSource? {
  let filter = [kTISPropertyInputSourceID as String: id] as CFDictionary
  return (TISCreateInputSourceList(filter, true)?.takeRetainedValue() as? [TISInputSource])?.first
}

func currentSourceID() -> String {
  let s = TISCopyCurrentKeyboardInputSource().takeRetainedValue()
  guard let v = TISGetInputSourceProperty(s, kTISPropertyInputSourceID) else { return "?" }
  return Unmanaged<CFString>.fromOpaque(v).takeUnretainedValue() as String
}

// MARK: - キー送信

// ANSI/JIS 共通の物理キー位置 (kVK_ANSI_*)
let keyCodes: [Character: CGKeyCode] = [
  "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
  "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "o": 31, "u": 32,
  "i": 34, "p": 35, "l": 37, "j": 38, "k": 40, "n": 45, "m": 46,
  "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "9": 25, "7": 26, "8": 28, "0": 29,
]
let specialCodes: [String: CGKeyCode] = [
  "Enter": 36, "Space": 49, "Tab": 48, "Backspace": 51, "ESC": 53,
  "Left": 123, "Right": 124, "Down": 125, "Up": 126,
]

let eventSource = CGEventSource(stateID: .hidSystemState)
var keyDelay: useconds_t = 40_000

func post(_ code: CGKeyCode, _ flags: CGEventFlags = []) {
  for down in [true, false] {
    let ev = CGEvent(keyboardEventSource: eventSource, virtualKey: code, keyDown: down)!
    ev.flags = flags
    ev.post(tap: .cghidEventTap)
    usleep(5_000)
  }
  usleep(keyDelay)
}

/// "Ctrl Shift f" / "Enter" / "a" のような Mozc 風のキー表記を 1 打鍵として送る
func press(_ spec: String) {
  var flags: CGEventFlags = []
  var key = ""
  for part in spec.split(separator: " ") {
    switch part.lowercased() {
    case "ctrl": flags.insert(.maskControl)
    case "shift": flags.insert(.maskShift)
    case "alt", "option": flags.insert(.maskAlternate)
    case "cmd": flags.insert(.maskCommand)
    default: key = String(part)
    }
  }
  if let c = specialCodes[key] {
    post(c, flags)
  } else if key.count == 1, let c = keyCodes[Character(key.lowercased())] {
    post(c, flags)
  } else {
    fatalError("unknown key: \(spec)")
  }
}

/// ローマ字などの文字列をそのまま打鍵する
func type(_ s: String) {
  for ch in s { press(String(ch)) }
}

// MARK: - TextEdit

@discardableResult
func osascript(_ src: String) -> String {
  var err: NSDictionary?
  let r = NSAppleScript(source: src)!.executeAndReturnError(&err)
  if let err { fatalError("AppleScript error: \(err)") }
  return r.stringValue ?? ""
}

func prepareTextEdit() {
  osascript("""
    tell application "TextEdit"
      activate
      make new document
    end tell
    """)
  usleep(800_000)
}

func clearDocument() {
  osascript(#"tell application "TextEdit" to set text of document 1 to """#)
  usleep(200_000)
}

func documentText() -> String {
  usleep(300_000)
  return osascript(#"tell application "TextEdit" to get text of document 1"#)
}

// MARK: - テストケース

struct Case {
  let name: String
  let note: String
  let steps: [String]  // "type:xxx" は文字列打鍵、それ以外は 1 打鍵
  let expected: String
}

let reading = "kokodehakimonowonugu"  // ここではきものをぬぐ
let many = { (k: String, n: Int) in Array(repeating: k, count: n) }

let cases: [Case] = [
  Case(name: "composition: C-g でキャンセル",
       note: "読み入力中の C-g (Cancel) で未確定文字列が消える",
       steps: ["type:aiu", "Ctrl g", "type:e", "Enter"],
       expected: "え"),
  Case(name: "composition: C-b / C-d / C-a / C-e / C-h",
       note: "読みの中でカーソル移動・削除 (MoveCursorLeft, Delete, MoveCursorToBeginning, MoveCursorToEnd, Backspace)",
       steps: ["type:aiueo", "Ctrl b", "Ctrl b", "Ctrl d", "Ctrl a", "Ctrl d", "Ctrl e", "Ctrl h", "Enter"],
       expected: "いう"),
  Case(name: "conversion: C-g で変換キャンセル",
       note: "変換中の C-g (追加した Cancel) で読みに戻る",
       steps: ["type:" + reading, "Space", "Ctrl g", "Enter"],
       expected: "ここではきものをぬぐ"),
  Case(name: "conversion: C-S-f で文節を伸ばす",
       note: "C-S-f (SegmentWidthExpand) を繰り返して 1 文節にし、C-j (DisplayAsHiragana) で全体がひらがなになる",
       steps: ["type:" + reading, "Space"] + many("Ctrl Shift f", 12) + ["Ctrl j", "Enter"],
       expected: "ここではきものをぬぐ"),
  Case(name: "conversion: C-S-b で縮める + C-e / C-a で文節移動",
       note: "1 文節にしてから C-S-b (SegmentWidthShrink) で末尾 1 文字を分割、C-e (SegmentFocusLast) → C-k でカタカナ、C-a (SegmentFocusFirst) → C-j でひらがな",
       steps: ["type:" + reading, "Space"] + many("Ctrl Shift f", 12)
         + ["Ctrl Shift b", "Ctrl e", "Ctrl k", "Ctrl a", "Ctrl j", "Enter"],
       expected: "ここではきものをぬグ"),
  Case(name: "conversion: C-f / C-b で文節移動",
       note: "末尾 1 文字を分割後、C-f (SegmentFocusRight) → C-k、C-b (SegmentFocusLeft) → C-j",
       steps: ["type:" + reading, "Space"] + many("Ctrl Shift f", 12)
         + ["Ctrl Shift b", "Ctrl f", "Ctrl k", "Ctrl b", "Ctrl j", "Enter"],
       expected: "ここではきものをぬグ"),
  Case(name: "conversion: C-n → C-p で元の候補に戻る",
       note: "C-n (ConvertNext) と C-p (ConvertPrev) が対になっていることを、C-n/C-p なしの結果との一致で確認する",
       steps: ["type:kanji", "Space", "Ctrl n", "Ctrl p", "Enter", "type:kanji", "Space", "Enter"],
       expected: "<first-half == second-half>"),
  Case(name: "precomposition: C-p / C-a はアプリに渡る",
       note: "IME オン・未入力時の C-p / C-a は IME が消費せず、TextEdit の前行移動・行頭移動になる",
       steps: ["type:a", "Enter", "Enter", "type:i", "Enter", "Ctrl p", "Ctrl a", "type:u", "Enter"],
       expected: "うあ\nい"),
]

// MARK: - 実行

guard AXIsProcessTrustedWithOptions(
  [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary)
else {
  print("アクセシビリティ権限がない。システム設定 → プライバシーとセキュリティ → アクセシビリティ で実行元のアプリを許可して再実行する。")
  exit(1)
}
guard let target = inputSource(sourceID) else {
  print("入力ソースが見つからない: \(sourceID)")
  exit(1)
}

let previous = currentSourceID()
prepareTextEdit()
var failed = 0
var ran = 0

for c in cases where only == nil || c.name.contains(only!) {
  clearDocument()
  TISSelectInputSource(target)
  usleep(300_000)
  for step in c.steps {
    if step.hasPrefix("type:") {
      type(String(step.dropFirst(5)))
    } else {
      press(step)
      if step == "Space" { usleep(200_000) }  // 変換を待つ
    }
  }
  let got = documentText()
  let ok: Bool
  if c.expected == "<first-half == second-half>" {
    let n = got.count / 2
    ok = got.count % 2 == 0 && got.prefix(n) == got.suffix(n) && n > 0
  } else {
    ok = got == c.expected
  }
  ran += 1
  if !ok { failed += 1 }
  print("\(ok ? "PASS" : "FAIL")  \(c.name)")
  if !ok {
    print("      note:     \(c.note)")
    print("      expected: \(c.expected.debugDescription)")
    print("      got:      \(got.debugDescription)")
  }
}

clearDocument()
if let prev = inputSource(previous) { TISSelectInputSource(prev) }
print("\n\(ran - failed)/\(ran) passed (input source: \(sourceID), current: \(currentSourceID()))")
exit(failed == 0 ? 0 : 1)
