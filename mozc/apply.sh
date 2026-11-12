#!/bin/sh
# out/config1.db を Google日本語入力 (または Mozc) の設定ディレクトリに配置し、変換サーバーを再起動する。
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
case "${1:-google}" in
  google) DIR="$HOME/Library/Application Support/Google/JapaneseInput"; PROC=GoogleJapaneseInputConverter ;;
  mozc)   DIR="$HOME/Library/Application Support/Mozc";                 PROC=MozcConverter ;;
  *) echo "usage: $0 [google|mozc]" >&2; exit 2 ;;
esac
mkdir -p "$DIR"
if [ -f "$DIR/config1.db" ]; then
  cp "$DIR/config1.db" "$DIR/config1.db.bak.$(date +%Y%m%d%H%M%S)"
fi
cp "$HERE/out/config1.db" "$DIR/config1.db"
killall "$PROC" 2>/dev/null || true   # MachServices でオンデマンド再起動される
echo "applied: $DIR/config1.db"
