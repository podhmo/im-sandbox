// IME オンの方法を試す小さなテスト。3つの方法を順に試して 'a' を打ち、
// TextBox に "あ" が入るかを見る。
using System;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Threading;

class T {
  [DllImport("imm32.dll")] static extern IntPtr ImmGetContext(IntPtr hWnd);
  [DllImport("imm32.dll")] static extern bool ImmReleaseContext(IntPtr hWnd, IntPtr hIMC);
  [DllImport("imm32.dll")] static extern bool ImmGetOpenStatus(IntPtr hIMC);
  [DllImport("imm32.dll")] static extern bool ImmSetOpenStatus(IntPtr hIMC, bool fOpen);
  [DllImport("imm32.dll")] static extern bool ImmGetConversionStatus(IntPtr hIMC, out int c, out int s);
  [DllImport("imm32.dll")] static extern bool ImmSetConversionStatus(IntPtr hIMC, int c, int s);
  [DllImport("imm32.dll")] static extern IntPtr ImmGetDefaultIMEWnd(IntPtr hWnd);
  [DllImport("user32.dll")] static extern IntPtr SendMessageW(IntPtr h, int m, IntPtr w, IntPtr l);

  [StructLayout(LayoutKind.Sequential)]
  struct KBD { public ushort wVk, wScan; public uint dwFlags, time; public IntPtr ex; }
  [StructLayout(LayoutKind.Explicit, Size = 40)]
  struct INP { [FieldOffset(0)] public int type; [FieldOffset(8)] public KBD ki; }
  [DllImport("user32.dll")] static extern uint SendInput(int n, INP[] p, int cb);

  const int IME_CMODE_NATIVE = 0x1, IME_CMODE_FULLSHAPE = 0x8;

  static void Pump(int ms) {
    var f = new DispatcherFrame();
    var t = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(ms) };
    t.Tick += (s, e) => { f.Continue = false; t.Stop(); };
    t.Start(); Dispatcher.PushFrame(f);
  }
  static void Key(ushort vk) {
    INP[] p = { new INP { type = 1, ki = new KBD { wVk = vk } },
                new INP { type = 1, ki = new KBD { wVk = vk, dwFlags = 2 } } };
    SendInput(2, p, Marshal.SizeOf(typeof(INP))); Pump(80);
  }

  [STAThread] static void Main() {
    var w = new Window { Width = 400, Height = 200, Topmost = true, Title = "probe" };
    var b = new TextBox { AcceptsReturn = true, FontSize = 24 };
    w.Content = b; w.Show(); w.Activate(); b.Focus(); Pump(400);
    var hwnd = new WindowInteropHelper(w).Handle;

    // 1. IMM32 でのオープン
    var himc = ImmGetContext(hwnd);
    Console.WriteLine("HIMC={0} open(before)={1}", himc, himc != IntPtr.Zero && ImmGetOpenStatus(himc));
    bool ok = himc != IntPtr.Zero && ImmSetOpenStatus(himc, true);
    int cv, sn;
    ImmGetConversionStatus(himc, out cv, out sn);
    Console.WriteLine("SetOpenStatus={0} conv(before)={1:x}", ok, cv);
    ImmSetConversionStatus(himc, IME_CMODE_NATIVE | IME_CMODE_FULLSHAPE, 0);
    ImmGetConversionStatus(himc, out cv, out sn);
    Console.WriteLine("conv(after)={0:x} open={1}", cv, ImmGetOpenStatus(himc));
    if (himc != IntPtr.Zero) ImmReleaseContext(hwnd, himc);
    Pump(300); b.Clear(); Key(0x41); Pump(200);
    Console.WriteLine("IMM後 text='{0}'", b.Text);
    if (b.Text == "あ") { Console.WriteLine("== IMM32 でオンできた"); Pump(500); return; }

    // 2. WPF InputMethod API
    InputMethod.SetPreferredImeState(b, InputMethodState.On);
    InputMethod.SetPreferredImeConversionMode(b, ImeConversionModeValues.Native);
    b.Focus(); Pump(400); b.Clear(); Key(0x41); Pump(200);
    Console.WriteLine("WPF後 text='{0}'", b.Text);
    if (b.Text == "あ") { Console.WriteLine("== WPF API でオンできた"); Pump(500); return; }

    // 3. 半角/全角キー (VK 0xF3) の打鍵
    b.Clear(); Key(0xF3); Pump(400); Key(0x41); Pump(200);
    Console.WriteLine("VK F3後 text='{0}'", b.Text);
    Console.WriteLine(b.Text == "あ" ? "== VK 0xF3 でオンできた" : "== どれも効かなかった");
    Pump(500);
  }
}
