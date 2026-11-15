# e2e.ps1 — e2e.sh の Windows (PowerShell) 版。
# E2E を、学習を無効にした設定で一時的に実行する。
# 実行中だけ config1.db を差し替え、終了時 (失敗・中断を含む) に元へ戻す。
#
# usage:
#   ./mozc/e2e.ps1 [custom|default] [--only <case名の一部>]
#
#   custom  : mozc/build.ps1 が生成するカスタムキーマップ (既定)
#   default : mozc 既定のキーマップ (Windows では session_keymap: MSIME。
#             テストが差分を検出できるかの確認用)
#
# history_learning_level: NO_HISTORY にすると、学習結果を使わず、新たな記録もしない
# (user_history_predictor / user_segment_history_rewriter / user_boundary_history_rewriter)。
# cform.db は NO_HISTORY 対象外なので学習ファイルごと退避する (e2e.sh と同じ設計)。
$ErrorActionPreference = "Stop"
$HERE = Split-Path -Parent $MyInvocation.MyCommand.Path
$ROOT = Split-Path -Parent $HERE
$OUT = Join-Path $HERE "out"
New-Item -ItemType Directory -Force $OUT | Out-Null

# ---- モードと残り引数 ----
$MODE = if ($args.Count -gt 0) { $args[0] } else { "custom" }
$rest = @()
if ($args.Count -gt 1) { $rest = $args[1..($args.Count - 1)] }
if ($rest.Count -gt 0 -and $rest[0] -eq "--") { $rest = $rest[1..($rest.Count - 1)] }

$DIR = Join-Path $env:USERPROFILE "AppData\LocalLow\Google\Google Japanese Input"
$PROC = "GoogleIMEJaConverter"
$e2eTextproto = Join-Path $OUT "e2e.textproto"

switch ($MODE) {
  "custom" {
    powershell -ExecutionPolicy Bypass -File (Join-Path $HERE "build.ps1") | Out-Null
    Copy-Item (Join-Path $OUT "config.textproto") $e2eTextproto -Force
  }
  "default" {
    # Windows の既定解決は MSIME。明示しておく (linux 版の `default` 相当)
    "session_keymap: MSIME" | Out-File -Encoding ascii $e2eTextproto
  }
  default { Write-Error "usage: e2e.ps1 [custom|default] [--only <case名>]"; exit 2 }
}
Add-Content -Encoding ascii $e2eTextproto "history_learning_level: NO_HISTORY"

$PROTO_DIR = Join-Path $HERE "third_party\mozc\protocol"
$e2edb = Join-Path $OUT "e2e.config1.db"
cmd /c "protoc -I `"$PROTO_DIR`" --encode=mozc.config.Config config.proto < `"$e2eTextproto`" > `"$e2edb`""
if ($LASTEXITCODE -ne 0) { throw "protoc --encode failed" }

# ---- ランナー (なければビルド) ----
$runner = Join-Path $OUT "mozc_e2e_win.exe"
if (-not (Test-Path $runner)) {
  $CSC = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
  $WPF = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\WPF"
  & $CSC /nologo /target:exe /platform:x64 /out:$runner `
    /r:"$WPF\PresentationFramework.dll" /r:"$WPF\PresentationCore.dll" `
    /r:"$WPF\WindowsBase.dll" /r:System.Xaml.dll `
    (Join-Path $ROOT "tools\mozc_e2e_win.cs")
  if ($LASTEXITCODE -ne 0) { throw "csc failed" }
}

# ---- 変換サーバー停止・設定差し替え・学習ファイル退避 ----
# 学習ファイル。Windows のファイル名は先頭ドット無し (history.db)。
# encrypt_key.db は履歴復号の鍵なので退避しない (消すと既存履歴が読めなくなる)。
$LEARN_FILES = @("cform.db", "segment.db", "boundary.db", "history.db", ".history.db")
$BACKUP = Join-Path $OUT "e2e.original.config1.db"
$LEARN_BACKUP = Join-Path $OUT "e2e.learning"

function Stop-Converter {
  Get-Process $PROC -ErrorAction SilentlyContinue | Stop-Process -Force
  $i = 0
  while (Get-Process $PROC -ErrorAction SilentlyContinue) {
    Start-Sleep -Milliseconds 100
    if (++$i -gt 50) { break }
  }
}

New-Item -ItemType Directory -Force $DIR | Out-Null
if (Test-Path (Join-Path $DIR "config1.db")) {
  Copy-Item (Join-Path $DIR "config1.db") $BACKUP -Force
} elseif (Test-Path $BACKUP) { Remove-Item $BACKUP }

try {
  Stop-Converter
  Copy-Item $e2edb (Join-Path $DIR "config1.db") -Force
  New-Item -ItemType Directory -Force $LEARN_BACKUP | Out-Null
  foreach ($f in $LEARN_FILES) {
    $p = Join-Path $DIR $f
    if (Test-Path $p) { Move-Item $p $LEARN_BACKUP -Force }
  }
  Write-Host "keymap: $MODE (history_learning_level: NO_HISTORY)"
  & $runner @rest
} finally {
  # 先にサーバーを止め、実行中に生成された学習ファイルを消してから退避分を戻す
  Stop-Converter
  foreach ($f in $LEARN_FILES) {
    $p = Join-Path $DIR $f
    if (Test-Path $p) { Remove-Item $p -Force }
  }
  if (Test-Path $LEARN_BACKUP) {
    Get-ChildItem $LEARN_BACKUP -Force | ForEach-Object { Move-Item $_.FullName $DIR -Force }
    Remove-Item $LEARN_BACKUP -Force -Recurse
  }
  if (Test-Path $BACKUP) { Copy-Item $BACKUP (Join-Path $DIR "config1.db") -Force }
  else { Remove-Item (Join-Path $DIR "config1.db") -Force -ErrorAction SilentlyContinue }
  Write-Host "restored: $DIR\config1.db"
}
