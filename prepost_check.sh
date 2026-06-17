#!/bin/bash
# prepost_check.sh — Автоматична перевірка перед постингом
# Запускає quality_gate.py + fingerprint_check.py послідовно
# Блокує публікацію якщо хоча б один скрипт не пройдено
#
# Використання:
#   bash prepost_check.sh post.txt
#   echo "Текст" | bash prepost_check.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QG="$SCRIPT_DIR/quality_gate.py"
FP="$SCRIPT_DIR/fingerprint_check.py"

# Кольори
RED='\033[91m'; GREEN='\033[92m'; YELLOW='\033[93m'
CYAN='\033[96m'; BOLD='\033[1m'; RESET='\033[0m'

echo ""
echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════════╗${RESET}"
echo -e "${CYAN}${BOLD}║          PRE-POST CHECK — ФІЛЬТР ПУБЛІКАЦІЙ          ║${RESET}"
echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════════════╝${RESET}"
echo ""

# Отримуємо текст
if [ -n "$1" ]; then
    TEXT_SOURCE="-f $1"
    echo -e "  📄 Файл: $1"
elif [ ! -t 0 ]; then
    TMPFILE=$(mktemp /tmp/prepost_XXXX.txt)
    cat > "$TMPFILE"
    TEXT_SOURCE="-f $TMPFILE"
    echo -e "  📄 Джерело: stdin"
else
    echo -e "${RED}❌ Вкажи файл або передай текст через stdin${RESET}"
    echo "   Використання: bash prepost_check.sh post.txt"
    echo "   або: echo 'текст' | bash prepost_check.sh"
    exit 2
fi

echo ""
echo -e "${BOLD}  ── КРОК 1: Quality Gate (якість тексту) ──────────────${RESET}"
echo ""

QG_EXIT=0
python3 "$QG" $TEXT_SOURCE --no-color 2>&1 || QG_EXIT=$?

echo ""
echo -e "${BOLD}  ── КРОК 2: Fingerprint Check (AI-штампи) ──────────────${RESET}"
echo ""

FP_EXIT=0
python3 "$FP" $TEXT_SOURCE --no-color --no-text 2>&1 || FP_EXIT=$?

# Прибираємо тимчасовий файл
[ -n "$TMPFILE" ] && rm -f "$TMPFILE"

echo ""
echo -e "${BOLD}  ════════════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}  ПІДСУМОК PRE-POST CHECK${RESET}"
echo -e "${BOLD}  ════════════════════════════════════════════════════════${RESET}"
echo ""

QG_STATUS="${GREEN}✅ ПРОЙДЕНО${RESET}"
FP_STATUS="${GREEN}✅ ПРОЙДЕНО${RESET}"
[ $QG_EXIT -ne 0 ] && QG_STATUS="${RED}❌ НЕ ПРОЙДЕНО${RESET}"
[ $FP_EXIT -ne 0 ] && FP_STATUS="${RED}❌ НЕ ПРОЙДЕНО${RESET}"

echo -e "  Quality Gate:         $QG_STATUS"
echo -e "  Fingerprint Check:    $FP_STATUS"
echo ""

if [ $QG_EXIT -eq 0 ] && [ $FP_EXIT -eq 0 ]; then
    echo -e "${GREEN}${BOLD}  🚀 ТЕКСТ ГОТОВИЙ ДО ПУБЛІКАЦІЇ${RESET}"
    echo ""
    exit 0
else
    echo -e "${RED}${BOLD}  🚫 ПУБЛІКАЦІЮ ЗАБЛОКОВАНО — виправ помилки вище${RESET}"
    echo ""
    exit 1
fi
