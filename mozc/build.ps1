# build.ps1 — build.sh の Windows (PowerShell) 版。
# keymap.tsv と config.base.textproto から out/config1.db を生成する。
#
# usage: ./mozc/build.ps1
#
# 依存: protoc (winget install Google.Protobuf) と config.proto。
# config.proto は import のない単独ファイル。既定では
# mozc/third_party/mozc/protocol/config.proto を使う
# (MOZC_PROTO_DIR 環境変数で mozc ソースの src/protocol を指定してもよい)。
$ErrorActionPreference = "Stop"
$HERE = Split-Path -Parent $MyInvocation.MyCommand.Path
$OUT = Join-Path $HERE "out"
New-Item -ItemType Directory -Force $OUT | Out-Null

$PROTO_DIR = if ($env:MOZC_PROTO_DIR) { $env:MOZC_PROTO_DIR } `
  else { Join-Path $HERE "third_party\mozc\protocol" }
$PROTO = Join-Path $PROTO_DIR "config.proto"
if (-not (Test-Path $PROTO)) { throw "config.proto がない: $PROTO" }

# 1. キーマップ (全体を自前で書く。docs/ja/article.html の P5)
$keymapPath = Join-Path $HERE "keymap.tsv"
Copy-Item $keymapPath (Join-Path $OUT "keymap.tsv") -Force

# 2. textproto を組み立てる (TSV は bytes フィールドに文字列として埋め込む)
$s = [IO.File]::ReadAllText($keymapPath, [Text.Encoding]::UTF8)
$s = $s.Replace("\", "\\").Replace("`"", "\`"").Replace("`t", "\t").Replace("`r`n", "\n").Replace("`n", "\n")
$textproto = Join-Path $OUT "config.textproto"
$body = @(
  [IO.File]::ReadAllText((Join-Path $HERE "config.base.textproto"), [Text.Encoding]::UTF8)
  "session_keymap: CUSTOM"
  "custom_keymap_table: `"$s`""
) -join "`n"
# protoc は BOM を解釈しないので UTF8 (BOMなし) で書く
[IO.File]::WriteAllText($textproto, $body, (New-Object Text.UTF8Encoding($false)))

# 3. バイナリにエンコード (PowerShell は < リダイレクトを持たないので cmd 経由)
$db = Join-Path $OUT "config1.db"
cmd /c "protoc -I `"$PROTO_DIR`" --encode=mozc.config.Config config.proto < `"$textproto`" > `"$db`""
if ($LASTEXITCODE -ne 0) { throw "protoc --encode failed" }
Write-Host "generated: $db"
