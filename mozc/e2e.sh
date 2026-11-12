#!/bin/sh
# E2E (tools/mozc_e2e_mac.swift) を、学習を無効にした設定で一時的に実行する。
# 実行中だけ config1.db を差し替え、終了時 (失敗・中断を含む) に元へ戻す。
#
# usage: ./mozc/e2e.sh [custom|kotoeri] [-- mozc_e2e_mac.swift への引数]
#   custom  : mozc/build.sh が生成するカスタムキーマップ (既定)
#   kotoeri : macOS 既定のキーマップ (テストが差分を検出できるかの確認用)
#
# アクセシビリティ権限のある端末 (iTerm2 など) から実行すること。
# history_learning_level: NO_HISTORY にすると、学習結果を使わず、新たな記録もしない
# (user_history_predictor / user_segment_history_rewriter / user_boundary_history_rewriter)。
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(dirname "$HERE")
MOZC=${MOZC:-"$(ghq root)/github.com/google/mozc"}
DIR="$HOME/Library/Application Support/Google/JapaneseInput"
PROC=GoogleJapaneseInputConverter
MODE=${1:-custom}
[ $# -gt 0 ] && shift
[ "${1:-}" = "--" ] && shift

OUT="$HERE/out"
mkdir -p "$OUT"
case "$MODE" in
  custom)
    "$HERE/build.sh" >/dev/null
    cp "$OUT/config.textproto" "$OUT/e2e.textproto" ;;
  kotoeri)
    echo 'session_keymap: KOTOERI' > "$OUT/e2e.textproto" ;;
  *) echo "usage: $0 [custom|kotoeri] [-- args]" >&2; exit 2 ;;
esac
echo 'history_learning_level: NO_HISTORY' >> "$OUT/e2e.textproto"
protoc -I "$MOZC/src/protocol" --encode=mozc.config.Config config.proto \
  < "$OUT/e2e.textproto" > "$OUT/e2e.config1.db"

BACKUP="$OUT/e2e.original.config1.db"
if [ -f "$DIR/config1.db" ]; then cp "$DIR/config1.db" "$BACKUP"; else rm -f "$BACKUP"; fi
restore() {
  if [ -f "$BACKUP" ]; then cp "$BACKUP" "$DIR/config1.db"; else rm -f "$DIR/config1.db"; fi
  killall "$PROC" 2>/dev/null || true
  echo "restored: $DIR/config1.db"
}
trap restore EXIT
trap 'exit 130' INT TERM

cp "$OUT/e2e.config1.db" "$DIR/config1.db"
killall "$PROC" 2>/dev/null || true
sleep 1
echo "keymap: $MODE (history_learning_level: NO_HISTORY)"
swift "$ROOT/tools/mozc_e2e_mac.swift" "$@"
