#!/bin/sh
# keymap.overrides.tsv と config.base.textproto から out/config1.db を生成する。
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
MOZC=${MOZC:-"$(ghq root)/github.com/google/mozc"}
OUT="$HERE/out"
mkdir -p "$OUT"

# 1. キーマップ = kotoeri.tsv (1行目のヘッダー込み) + 差分
cat "$MOZC/src/data/keymap/kotoeri.tsv" "$HERE/keymap.overrides.tsv" > "$OUT/keymap.tsv"

# 2. textproto を組み立てる (TSV は bytes フィールドに文字列として埋め込む)
{
  cat "$HERE/config.base.textproto"
  echo 'session_keymap: CUSTOM'
  python3 -I -c '
import sys
s = open(sys.argv[1], encoding="utf-8").read()
s = s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\t", "\\t").replace("\n", "\\n")
print("custom_keymap_table: \"" + s + "\"")
' "$OUT/keymap.tsv"
} > "$OUT/config.textproto"

# 3. バイナリにエンコード
protoc -I "$MOZC/src/protocol" --encode=mozc.config.Config config.proto \
  < "$OUT/config.textproto" > "$OUT/config1.db"
echo "generated: $OUT/config1.db"
