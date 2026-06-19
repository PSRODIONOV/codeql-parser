#!/bin/bash
# Запускает main.py и мониторит RSS память процесса каждую секунду.
cd /mnt/f/codeql-parser

OUT_DIR="reports-nginx"
MEMLOG="mem_trace.log"
: > "$MEMLOG"

# Запускаем анализ в фоне
python3 main.py databases/nginx-db \
    -o "$OUT_DIR" \
    --language cpp \
    --pattern '%nginx%' \
    --codeql codeql-linux/codeql \
    > analysis_run.log 2>&1 &
PYPID=$!
echo "Запущен python PID=$PYPID"

PEAK=0
while kill -0 $PYPID 2>/dev/null; do
    # Суммарный RSS всего дерева процессов (python + дочерние java/codeql)
    TOTAL_KB=$(ps -o rss= --ppid $PYPID 2>/dev/null | awk '{s+=$1} END {print s}')
    SELF_KB=$(ps -o rss= -p $PYPID 2>/dev/null)
    TOTAL_KB=$(( ${TOTAL_KB:-0} + ${SELF_KB:-0} ))
    TOTAL_MB=$(( TOTAL_KB / 1024 ))
    if [ "$TOTAL_MB" -gt "$PEAK" ]; then PEAK=$TOTAL_MB; fi
    # Последняя строка лога анализа
    LASTLOG=$(tail -1 analysis_run.log 2>/dev/null)
    TS=$(date +%H:%M:%S)
    echo "[$TS] RSS=${TOTAL_MB}MB PEAK=${PEAK}MB | $LASTLOG" >> "$MEMLOG"
    sleep 1
done

echo "=== ЗАВЕРШЕНО. PEAK=${PEAK}MB ===" >> "$MEMLOG"
echo "PEAK=${PEAK}MB"
wait $PYPID
echo "Exit code: $?"
