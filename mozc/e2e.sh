#!/bin/sh
# E2E を、学習を無効にした設定で一時的に実行する。
# 実行中だけ config1.db を差し替え、終了時 (失敗・中断を含む) に元へ戻す。
#
# usage:
#   ./mozc/e2e.sh [custom|kotoeri] [-- args]   (macOS: tools/mozc_e2e_mac.swift)
#   ./mozc/e2e.sh linux [custom|default] [-- args]  (Linux: tools/mozc_e2e_fcitx5.py)
#
#   custom  : mozc/build.sh が生成するカスタムキーマップ (既定)
#   kotoeri : macOS 既定のキーマップ (テストが差分を検出できるかの確認用)
#   default : mozc 本体の既定キーマップ (同上。session_keymap を書かない)
#
# アクセシビリティ権限のある端末 (iTerm2 など) から実行すること。
# Linux では fcitx5 が起動していること (fcitx5 -d --disable=wayland)。
# history_learning_level: NO_HISTORY にすると、学習結果を使わず、新たな記録もしない
# (user_history_predictor / user_segment_history_rewriter / user_boundary_history_rewriter)。
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(dirname "$HERE")
MOZC=${MOZC:-"$(ghq root)/github.com/google/mozc"}
OUT="$HERE/out"
mkdir -p "$OUT"

case "${1:-}" in
  linux)
    shift
    MODE=${1:-custom}
    [ $# -gt 0 ] && shift
    [ "${1:-}" = "--" ] && shift
    DIR="$HOME/.config/mozc"
    PROC=mozc_server
    case "$MODE" in
      custom)
        "$HERE/build.sh" >/dev/null
        cp "$OUT/config.textproto" "$OUT/e2e.textproto" ;;
      default)
        : > "$OUT/e2e.textproto" ;;
      *) echo "usage: $0 linux [custom|default] [-- args]" >&2; exit 2 ;;
    esac
    RUNNER="python3 $ROOT/tools/mozc_e2e_fcitx5.py"
    ;;
  *)
    MODE=${1:-custom}
    [ $# -gt 0 ] && shift
    [ "${1:-}" = "--" ] && shift
    DIR="$HOME/Library/Application Support/Google/JapaneseInput"
    PROC=GoogleJapaneseInputConverter
    case "$MODE" in
      custom)
        "$HERE/build.sh" >/dev/null
        cp "$OUT/config.textproto" "$OUT/e2e.textproto" ;;
      kotoeri)
        echo 'session_keymap: KOTOERI' > "$OUT/e2e.textproto" ;;
      *) echo "usage: $0 [custom|kotoeri] [-- args]" >&2; exit 2 ;;
    esac
    RUNNER="swift $ROOT/tools/mozc_e2e_mac.swift"
    ;;
esac

# GUI e2e 等、別ランナーで同じ隔離 (NO_HISTORY + 学習ファイル退避) を使う場合:
#   E2E_RUNNER="python3 tools/mozc_e2e_gui.py x11" ./mozc/e2e.sh linux custom
if [ -n "${E2E_RUNNER:-}" ]; then RUNNER="$E2E_RUNNER"; fi

echo 'history_learning_level: NO_HISTORY' >> "$OUT/e2e.textproto"
protoc -I "$MOZC/src/protocol" --encode=mozc.config.Config config.proto \
  < "$OUT/e2e.textproto" > "$OUT/e2e.config1.db"

BACKUP="$OUT/e2e.original.config1.db"
LEARN_BACKUP="$OUT/e2e.learning"
if [ -f "$DIR/config1.db" ]; then cp "$DIR/config1.db" "$BACKUP"; else rm -f "$BACKUP"; fi
restore() {
  if [ -f "$BACKUP" ]; then cp "$BACKUP" "$DIR/config1.db"; else rm -f "$DIR/config1.db"; fi
  if [ -d "$LEARN_BACKUP" ]; then
    mv "$LEARN_BACKUP"/* "$LEARN_BACKUP"/.[!.]* "$DIR/" 2>/dev/null || true
    rmdir "$LEARN_BACKUP" 2>/dev/null || true
  fi
  killall "$PROC" 2>/dev/null || true
  echo "restored: $DIR/config1.db"
}
trap restore EXIT
trap 'exit 130' INT TERM

cp "$OUT/e2e.config1.db" "$DIR/config1.db"
killall "$PROC" 2>/dev/null || true
# cform.db (文字種の学習) は NO_HISTORY の対象外なので、学習ファイルごと退避する。
# NO_HISTORY が効く segment.db / boundary.db / .history.db も念のため一緒に退避。
mkdir -p "$LEARN_BACKUP"
for f in cform.db segment.db boundary.db .history.db; do
  [ -f "$DIR/$f" ] && mv "$DIR/$f" "$LEARN_BACKUP/" || true
done
sleep 1
echo "keymap: $MODE (history_learning_level: NO_HISTORY)"
$RUNNER "$@"
