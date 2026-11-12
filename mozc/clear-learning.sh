#!/bin/sh
# Google日本語入力 / Mozc の学習データを消去する (GUI の「履歴を消去」相当)。
# 削除ではなく mozc/out/learning-backup-<日時>/ へ退避するので、戻すこともできる。
#
# usage: ./mozc/clear-learning.sh [google|mozc]
#
# 対象 (GUI のボタンは CLEAR_USER_HISTORY と CLEAR_USER_PREDICTION を送る):
#   segment.db   候補の学習          (rewriter/user_segment_history_rewriter.cc)
#   boundary.db  文節区切りの学習    (rewriter/user_boundary_history_rewriter.cc)
#   cform.db     全角/半角の学習     (config/character_form_manager.cc)
#   .history.db  予測入力の履歴      (prediction/user_history_storage.cc, .encrypt_key.db で暗号化)
# 対象外: config1.db (設定), user_dictionary.db (ユーザー辞書), .encrypt_key.db (鍵)
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
case "${1:-google}" in
  google) DIR="$HOME/Library/Application Support/Google/JapaneseInput"; PROC=GoogleJapaneseInputConverter ;;
  mozc)   DIR="$HOME/Library/Application Support/Mozc";                 PROC=MozcConverter ;;
  *) echo "usage: $0 [google|mozc]" >&2; exit 2 ;;
esac
FILES="segment.db boundary.db cform.db .history.db"
BACKUP="$HERE/out/learning-backup-$(date +%Y%m%d%H%M%S)"

stop_server() {
  killall "$PROC" 2>/dev/null || true
  i=0
  while pgrep -x "$PROC" >/dev/null 2>&1; do
    i=$((i + 1)); [ $i -gt 50 ] && { echo "error: $PROC が止まらない" >&2; exit 1; }
    sleep 0.1
  done
}

# 1. サーバーを止める (メモリ上の学習がファイルへ書き戻されないように、先に止める)
stop_server
# 2. 学習データを退避
mkdir -p "$BACKUP"
for f in $FILES; do
  if [ -f "$DIR/$f" ]; then mv "$DIR/$f" "$BACKUP/"; echo "moved: $f"; fi
done
# 3. 退避中に IME が使われてサーバーが古いデータを読み込んだ場合に備え、もう一度止める
stop_server
echo "backup: $BACKUP"
echo "戻すとき: killall $PROC; cp -p \"$BACKUP\"/* \"$BACKUP\"/.history.db \"$DIR\"/ 2>/dev/null; killall $PROC"
