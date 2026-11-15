# clear-learning.ps1 — clear-learning.sh の Windows (PowerShell) 版。
# Google日本語入力の学習データを消去する (GUI の「履歴を消去」相当)。
# 削除ではなく mozc/out/learning-backup-<日時>/ へ退避するので、戻すこともできる。
#
# usage: ./mozc/clear-learning.ps1
#
# 対象 (GUI のボタンは CLEAR_USER_HISTORY と CLEAR_USER_PREDICTION を送る):
#   segment.db   候補の学習          (rewriter/user_segment_history_rewriter.cc)
#   boundary.db  文節区切りの学習    (rewriter/user_boundary_history_rewriter.cc)
#   cform.db     全角/半角の学習     (config/character_form_manager.cc)
#   history.db   予測入力の履歴      (prediction/user_history_storage.cc, encrypt_key.db で暗号化)
#   ※ Windows のファイル名は先頭ドット無し (mac/linux は .history.db)
# 対象外: config1.db (設定), user_dictionary.db (ユーザー辞書), encrypt_key.db (鍵)
$ErrorActionPreference = "Stop"
$HERE = Split-Path -Parent $MyInvocation.MyCommand.Path
$DIR = Join-Path $env:USERPROFILE "AppData\LocalLow\Google\Google Japanese Input"
$PROC = "GoogleIMEJaConverter"
$FILES = @("segment.db", "boundary.db", "cform.db", "history.db", ".history.db")
$BACKUP = Join-Path $HERE ("out\learning-backup-" + (Get-Date -Format "yyyyMMddHHmmss"))

function Stop-Converter {
  Get-Process $PROC -ErrorAction SilentlyContinue | Stop-Process -Force
  $i = 0
  while (Get-Process $PROC -ErrorAction SilentlyContinue) {
    Start-Sleep -Milliseconds 100
    if (++$i -gt 50) { throw "$PROC が止まらない" }
  }
}

# 1. サーバーを止める (メモリ上の学習がファイルへ書き戻されないように、先に止める)
Stop-Converter
# 2. 学習データを退避
New-Item -ItemType Directory -Force $BACKUP | Out-Null
foreach ($f in $FILES) {
  $p = Join-Path $DIR $f
  if (Test-Path $p) { Move-Item $p $BACKUP -Force; Write-Host "moved: $f" }
}
# 3. 退避中に IME が使われてサーバーが古いデータを読み込んだ場合に備え、もう一度止める
Stop-Converter
Write-Host "backup: $BACKUP"
Write-Host "戻すとき: Get-Process $PROC | Stop-Process -Force; Copy-Item `"$BACKUP\*`" `"$DIR\`" -Force; Get-Process $PROC | Stop-Process -Force"
