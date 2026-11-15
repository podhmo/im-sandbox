// mozc_e2e_win.cs — Windows 上の Google日本語入力 (Mozc) に実際のキーイベントを送り、
// 自作プローブ (WPF TextBox) の内容でキーマップの動作を確認する E2E。
// mozc_e2e_mac.swift / mozc_e2e_fcitx5.py の Windows 版。
//
// ビルド: e2e.ps1 が自動で行う
//   csc /target:exe /out:mozc\out\mozc_e2e_win.exe /r:WPF\PresentationFramework.dll ...
// 実行: mozc\out\mozc_e2e_win.exe [--only <case名の一部>]
//
// 前提:
//   - Google日本語入力がインストール済みであること
//   - 学習の影響を避けるため history_learning_level: NO_HISTORY の config1.db を
//     適用した状態で実行すること (mozc/e2e.ps1 経由が推奨)
//   - 「Ctrl+Shift による入力言語切り替え」ホットキーは無効化してあること
//     (設定 → 時刻と言語 → 入力 → 詳細なキーボード設定 → 入力言語のホットキー)
//
// 仕組み:
//   - ITfInputProcessorProfileMgr.ActivateProfile で Google日本語入力を有効化
//     (CLSID/Profile GUID は docs/sketch/ja/mozc-e2e-windows.md 参照)
//   - 自作の WPF ウィンドウを最前面にして SendInput でキーイベントを送る
//   - IME のオン・変換モードは WPF の InputMethod API (TSF compartment) で設定
//   - IME が消費したキーは TextBox に届かず、転送されたキーは PreviewKeyDown に
//     現れるので、「アプリに渡るか」の判定に使う (fcitx5 版の ForwardKey 相当)
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Threading;

class E2E {
  // ---------- SendInput ----------
  [StructLayout(LayoutKind.Sequential)]
  struct KEYBDINPUT { public ushort wVk, wScan; public uint dwFlags, time; public IntPtr dwExtraInfo; }
  // INPUT は共用体 (MOUSEINPUT 32B が最大)。x64 では type(4)+pad(4)+union(32)=40B
  [StructLayout(LayoutKind.Explicit, Size = 40)]
  struct INPUT { [FieldOffset(0)] public int type; [FieldOffset(8)] public KEYBDINPUT ki; }
  [DllImport("user32.dll", SetLastError = true)]
  static extern uint SendInput(int n, INPUT[] p, int cb);

  const int INPUT_KEYBOARD = 1;
  const uint KEYEVENTF_KEYUP = 0x0002;
  const ushort VK_CONTROL = 0x11, VK_SHIFT = 0x10, VK_MENU = 0x12;

  static readonly Dictionary<string, ushort> VK = new Dictionary<string, ushort> {
    { "Enter", 0x0D }, { "Space", 0x20 }, { "Tab", 0x09 }, { "Backspace", 0x08 },
    { "ESC", 0x1B }, { "Delete", 0x2E },
    { "Left", 0x25 }, { "Up", 0x26 }, { "Right", 0x27 }, { "Down", 0x28 },
    { "Home", 0x24 }, { "End", 0x23 }, { "PageUp", 0x21 }, { "PageDown", 0x22 },
    // JIS キーボード固有の VK。US 配列には物理キーが無いが SendInput なら送れる
    { "Zenkaku_Hankaku", 0xF3 }, // VK_OEM_AUTO (半角/全角)
    { "Muhenkan", 0xEB },        // VK_OEM_NEC_PI (無変換)
    { "Henkan", 0xFF },          // InitFn で VK_CONVERT 0x1C に入れ替える
    { "Eisu", 0xF0 },            // VK_DBE_ALPHANUMERIC
    { "Hiragana", 0xF2 },        // VK_DBE_HIRAGANA
    { "Katakana", 0xF1 },        // VK_DBE_KATAKANA
  };
  static void InitFn() { for (int i = 1; i <= 24; i++) VK["F" + i] = (ushort)(0x6F + i); VK["Henkan"] = 0x1C; }

  // ---------- IMM32 (IME のオン / 変換モード) ----------
  [DllImport("imm32.dll")] static extern IntPtr ImmGetContext(IntPtr hWnd);
  [DllImport("imm32.dll")] static extern bool ImmReleaseContext(IntPtr hWnd, IntPtr hIMC);
  [DllImport("imm32.dll")] static extern bool ImmGetOpenStatus(IntPtr hIMC);
  [DllImport("imm32.dll")] static extern bool ImmSetOpenStatus(IntPtr hIMC, bool fOpen);
  [DllImport("imm32.dll")] static extern bool ImmGetConversionStatus(IntPtr hIMC, out int c, out int s);
  [DllImport("imm32.dll")] static extern bool ImmSetConversionStatus(IntPtr hIMC, int c, int s);
  const int IME_CMODE_NATIVE = 0x1, IME_CMODE_FULLSHAPE = 0x8;

  static IntPtr hwnd;
  // IME をオン・ひらがなモードにする (TSF TIP でも IMM/TSF ブリッジ経由で効く。probe_ime_on で確認)
  static void EnsureImeOn() {
    var himc = ImmGetContext(hwnd);
    if (himc != IntPtr.Zero) {
      ImmSetOpenStatus(himc, true);
      ImmSetConversionStatus(himc, IME_CMODE_NATIVE | IME_CMODE_FULLSHAPE, 0);
      ImmReleaseContext(hwnd, himc);
    }
  }

  static int keyDelay = 60;

  static void SendVk(ushort vk, bool up) {
    INPUT[] p = { new INPUT { type = INPUT_KEYBOARD,
      ki = new KEYBDINPUT { wVk = vk, dwFlags = up ? KEYEVENTF_KEYUP : 0 } } };
    if (SendInput(1, p, Marshal.SizeOf(typeof(INPUT))) != 1)
      Console.WriteLine("SendInput failed");
  }

  // "Ctrl Shift m" / "Enter" / "a" のような Mozc 風キー表記を 1 打鍵として送る
  static void Press(string spec) {
    var mods = new List<ushort>();
    string key = "";
    foreach (var part in spec.Split(' ')) {
      switch (part) {
        case "Ctrl": mods.Add(VK_CONTROL); break;
        case "Shift": mods.Add(VK_SHIFT); break;
        case "Alt": mods.Add(VK_MENU); break;
        default: key = part; break;
      }
    }
    ushort vk;
    if (VK.TryGetValue(key, out vk)) { }
    else if (key.Length == 1 && char.IsLetterOrDigit(key[0]))
      vk = (ushort)char.ToUpperInvariant(key[0]);
    else
      throw new Exception("unknown key: " + spec);
    foreach (var m in mods) SendVk(m, false);
    SendVk(vk, false); SendVk(vk, true);
    foreach (var m in mods) SendVk(m, true);
    Pump(keyDelay);
    if (key == "Space") Pump(250); // 変換を待つ
  }

  static void Type(string s) { foreach (var ch in s) Press(ch.ToString()); }

  // ---------- メッセージポンプ ----------
  static void Pump(int ms) {
    var frame = new DispatcherFrame();
    var t = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(ms) };
    t.Tick += (s, e) => { frame.Continue = false; t.Stop(); };
    t.Start();
    Dispatcher.PushFrame(frame);
  }

  // ---------- テストケース (mozc_e2e_fcitx5.py CASES の移植) ----------
  class Case {
    public string name, note, expected;
    public string[] steps;
    public string[] forwards = new string[0];
  }

  static List<string> keylog = new List<string>(); // アプリに届いたキー (PreviewKeyDown)
  static TextBox box;

  static string SpecName(KeyEventArgs e) {
    // 修飾キー単体の押下は転送判定の対象外 (ノイズになるだけ)
    switch (e.Key) {
      case Key.LeftCtrl: case Key.RightCtrl:
      case Key.LeftShift: case Key.RightShift:
      case Key.LeftAlt: case Key.RightAlt:
        return null;
    }
    string k = e.Key == Key.ImeProcessed ? "?" : e.Key.ToString().ToLowerInvariant();
    var mods = "";
    if ((Keyboard.Modifiers & ModifierKeys.Control) != 0) mods += "Ctrl ";
    if ((Keyboard.Modifiers & ModifierKeys.Shift) != 0) mods += "Shift ";
    if ((Keyboard.Modifiers & ModifierKeys.Alt) != 0) mods += "Alt ";
    switch (k) {
      case "return": k = "Enter"; break;
      case "back": k = "Backspace"; break;
      case "escape": k = "ESC"; break;
      case "oemauto": k = "Zenkaku_Hankaku"; break;
    }
    return (mods + k).Trim();
  }

  static Case[] CASES;
  static void InitCases() {
    string reading = "kokodehakimonowonugu"; // ここではきものをぬぐ
    var expand = new List<string>();
    for (int i = 0; i < 12; i++) expand.Add("Ctrl o");
    CASES = new Case[] {
      new Case { name = "composition: C-g でキャンセル",
        note = "読み入力中の C-g (Cancel) で未確定文字列が消える",
        steps = new[] { "type:aiu", "Ctrl g", "type:e", "Enter" },
        expected = "え" },
      new Case { name = "composition: C-b / C-d / C-a / C-e / C-h",
        note = "読みの中でカーソル移動・削除",
        steps = new[] { "type:aiueo", "Ctrl b", "Ctrl b", "Ctrl d",
                        "Ctrl a", "Ctrl d", "Ctrl e", "Ctrl h", "Enter" },
        expected = "いう" },
      new Case { name = "composition: C-n で変換に進む (PredictAndConvert)",
        note = "読み入力中の C-n で予測変換に入り、確定すると読み以外が確定する",
        steps = new[] { "type:kanji", "Ctrl n", "Enter" },
        expected = "<not-hiragana>" },
      new Case { name = "conversion: C-g で変換キャンセル",
        note = "変換中の C-g (Cancel) で読みに戻る",
        steps = new[] { "type:" + reading, "Space", "Ctrl g", "Enter" },
        expected = "ここではきものをぬぐ" },
      new Case { name = "conversion: C-o で文節を伸ばす",
        note = "C-o (SegmentWidthExpand) を繰り返して 1 文節にし C-j で全体がひらがな",
        steps = Concat(new[] { "type:" + reading, "Space" }, expand.ToArray(),
                       new[] { "Ctrl j", "Enter" }),
        expected = "ここではきものをぬぐ" },
      new Case { name = "conversion: C-i で縮める + C-e / C-a で文節移動",
        note = "1 文節にしてから C-i で末尾を分割、C-e → C-q、C-a → C-j",
        steps = Concat(new[] { "type:" + reading, "Space" }, expand.ToArray(),
                       new[] { "Ctrl i", "Ctrl e", "Ctrl q", "Ctrl a", "Ctrl j", "Enter" }),
        expected = "ここではきものをぬグ" },
      new Case { name = "conversion: C-f / C-b で文節移動",
        note = "末尾を分割後、C-f → C-q、C-b → C-j",
        steps = Concat(new[] { "type:" + reading, "Space" }, expand.ToArray(),
                       new[] { "Ctrl i", "Ctrl f", "Ctrl q", "Ctrl b", "Ctrl j", "Enter" }),
        expected = "ここではきものをぬグ" },
      new Case { name = "conversion: C-S-b / C-S-f でも文節を伸縮",
        note = "Ctrl+Shift+文字が Shift 保持で届くかの検証でもある",
        steps = Concat(new[] { "type:" + reading, "Space" },
                       Rep("Ctrl Shift f", 12),
                       new[] { "Ctrl Shift b", "Ctrl e", "Ctrl q", "Ctrl a", "Ctrl j", "Enter" }),
        expected = "ここではきものをぬグ" },
      new Case { name = "conversion: Tab も文節を縮める",
        note = "Tab (SegmentWidthShrink)。C-i との区別がついていることも検証",
        steps = Concat(new[] { "type:" + reading, "Space" }, expand.ToArray(),
                       new[] { "Tab", "Ctrl e", "Ctrl q", "Ctrl a", "Ctrl j", "Enter" }),
        expected = "ここではきものをぬグ" },
      new Case { name = "conversion: C-S-m で先頭の文節だけ確定",
        note = "C-S-m (CommitOnlyFirstSegment) で先頭文節 (漢字) だけ確定し、残りは変換中のまま。"
               + " 続く C-g で残りを取消→読みのまま Enter 確定で「漢字をかく」になる。"
               + " 全確定のときは C-g がアプリに転送される (keylog に残る) のでそちらでも判定",
        steps = new[] { "type:kanjiwokaku", "Space", "Ctrl Shift m", "Ctrl g", "Enter" },
        expected = "<commit-first-seg>" },
      new Case { name = "conversion: Shift Enter も先頭の文節だけ確定",
        note = "Shift Enter (CommitOnlyFirstSegment)。C-S-m と同じコマンド",
        steps = new[] { "type:kanjiwokaku", "Space", "Shift Enter", "Ctrl g", "Enter" },
        expected = "<commit-first-seg>" },
      new Case { name = "conversion: C-n → C-p で元の候補に戻る",
        note = "ConvertNext と ConvertPrev が対。押さなかった場合と結果が一致する",
        steps = new[] { "type:kanji", "Space", "Ctrl n", "Ctrl p", "Enter",
                        "type:kanji", "Space", "Enter" },
        expected = "<halves-equal>" },
      new Case { name = "precomposition: C-p / C-a はアプリに渡る",
        note = "IMEオン・未入力時の C-p / C-a は消費されず転送される",
        steps = new[] { "Ctrl p", "Ctrl a" },
        expected = "", forwards = new[] { "Ctrl p", "Ctrl a" } },
      new Case { name = "directinput: 半角/全角キーで IME オン/オフ",
        note = "Zenkaku_Hankaku (VK 0xF3) で DIRECT へ。DIRECT では打鍵が転送され、もう一度押すと IMEOn",
        steps = new[] { "Zenkaku_Hankaku", "type:a", "Zenkaku_Hankaku", "type:a", "Enter" },
        expected = "aあ", forwards = new[] { "a" } },
    };
  }
  static string[] Concat(params string[][] xs) {
    var r = new List<string>(); foreach (var x in xs) r.AddRange(x); return r.ToArray();
  }
  static string[] Rep(string s, int n) { var r = new string[n]; for (int i = 0; i < n; i++) r[i] = s; return r; }

  // ---------- 本体 ----------
  [STAThread]
  static int Main(string[] args) {
    string only = null;
    for (int i = 0; i < args.Length; i++) {
      if (args[i] == "--only" && i + 1 < args.Length) only = args[++i];
      else { Console.Error.WriteLine("unknown arg: " + args[i]); return 2; }
    }
    InitFn(); InitCases();

    // 前提: 入力言語は ja、既定 TIP (Get-WinUserLanguageList の先頭) が
    // Google日本語入力であること。違う場合は先に Win+Space 等で選び直すこと。
    var win = new Window {
      Title = "mozc-e2e-win", Width = 500, Height = 300,
      Topmost = true, WindowStartupLocation = WindowStartupLocation.CenterScreen,
    };
    box = new TextBox {
      AcceptsReturn = true, FontSize = 20,
      VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
    };
    box.PreviewKeyDown += (s, e) => { var n = SpecName(e); if (n != null) keylog.Add(n); };
    win.Content = box;
    win.Show();
    win.Activate();
    box.Focus();
    hwnd = new System.Windows.Interop.WindowInteropHelper(win).Handle;

    EnsureImeOn();
    Pump(500);

    int ran = 0, failed = 0;
    foreach (var c in CASES) {
      if (only != null && !c.name.Contains(only)) continue;
      // リセット: テキスト消去 + IME をひらがな入力に戻す
      box.Clear(); keylog.Clear();
      box.Focus();
      EnsureImeOn();
      Pump(300);

      foreach (var s in c.steps) {
        if (s.StartsWith("type:")) Type(s.Substring(5));
        else Press(s);
      }
      Pump(300);
      string got = box.Text;

      bool ok;
      switch (c.expected) {
        case "<halves-equal>":
          int n = got.Length / 2;
          ok = got.Length % 2 == 0 && n > 0 && got.Substring(0, n) == got.Substring(n);
          break;
        case "<not-hiragana>": ok = got.Length > 0 && got != "かんじ"; break;
        case "<commit-first-seg>":
          // 先頭文節が確定 (漢字) して残りがひらがな確定になる。
          // 全確定だった場合は C-g がアプリに転送される (TextBox.Text は
          // preedit も含むので文字列だけでは確定の分割を判定できない)
          ok = got.Contains("漢字") && got.EndsWith("かく") && !keylog.Contains("Ctrl g");
          break;
        default: ok = got == c.expected; break;
      }
      foreach (var f in c.forwards)
        if (!keylog.Contains(f)) ok = false;

      ran++;
      if (!ok) failed++;
      Console.WriteLine("{0}  {1}", ok ? "PASS" : "FAIL", c.name);
      if (!ok) {
        Console.WriteLine("      note:     {0}", c.note);
        Console.WriteLine("      expected: {0}  forwards=[{1}]", c.expected, string.Join(" ", c.forwards));
        Console.WriteLine("      got:      \"{0}\"  keylog=[{1}]",
                          got, string.Join(" ", keylog));
      }
    }

    {
      var himc = ImmGetContext(hwnd);
      if (himc != IntPtr.Zero) { ImmSetOpenStatus(himc, false); ImmReleaseContext(hwnd, himc); }
    }
    Console.WriteLine("\n{0}/{1} passed", ran - failed, ran);
    Pump(100);
    return failed == 0 ? 0 : 1;
  }
}
