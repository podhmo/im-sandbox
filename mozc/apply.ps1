# apply.ps1 — apply.sh の Windows (PowerShell) 版。
# out/config1.db を Google日本語入力 (または OSS Mozc) の設定ディレクトリに配置し、
# 変換サーバーを再起動する。
#
# usage: ./mozc/apply.ps1 [google|mozc]
$ErrorActionPreference = "Stop"
$HERE = Split-Path -Parent $MyInvocation.MyCommand.Path
$LOCALLOW = Join-Path $env:USERPROFILE "AppData\LocalLow"

switch ($args[0]) {
  "mozc"   { $DIR = Join-Path $LOCALLOW "Mozc";                        $PROC = "mozc_server" }
  default  { $DIR = Join-Path $LOCALLOW "Google\Google Japanese Input"; $PROC = "GoogleIMEJaConverter" }
}
$db = Join-Path $HERE "out\config1.db"
if (-not (Test-Path $db)) { throw "$db がない。先に build.ps1 を実行する" }

New-Item -ItemType Directory -Force $DIR | Out-Null
$target = Join-Path $DIR "config1.db"
if (Test-Path $target) {
  Copy-Item $target "$target.bak.$(Get-Date -Format yyyyMMddHHmmss)"
}
Copy-Item $db $target -Force

# 変換サーバーは起動時に config1.db を読む。止めても次回使用時に自動再起動される
Get-Process $PROC -ErrorAction SilentlyContinue | Stop-Process -Force
Write-Host "applied: $target"
