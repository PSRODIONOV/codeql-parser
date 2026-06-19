#!/bin/bash
# Применение нормализации прав (WSL-сторона, требует metadata на DrvFs).
# Список эталонных исполняемых файлов нужно сгенерировать ОТДЕЛЬНО через
# Git Bash (см. normalize_perms_genlist.sh) — НЕ через WSL/find: WSL без
# реальной EA-метки на файле отдаёт permissive-результат "как если бы 777"
# даже с metadata, поэтому сам список нельзя строить через WSL stat.
#
# Использование:
#   bash normalize_perms_apply.sh <целевой-каталог> <файл-со-списком>
set -e

TARGET="$1"
EXEC_LIST="$2"

if [ -z "$TARGET" ] || [ -z "$EXEC_LIST" ]; then
  echo "Использование: $0 <целевой-каталог> <файл-со-списком-исполняемых>"
  exit 1
fi

cd "$TARGET"

echo "[1] Базовая нормализация: файлы -> 644, каталоги -> 755 ..."
find . -type f -exec chmod 644 {} +
find . -type d -exec chmod 755 {} +

echo "[2] Восстановление +x по эталонному списку ($(wc -l < "$EXEC_LIST") путей) ..."
restored=0
missing=0
while IFS= read -r rel; do
  [ -z "$rel" ] && continue
  if [ -f "$rel" ]; then
    chmod +x "$rel"
    restored=$((restored+1))
  else
    missing=$((missing+1))
  fi
done < "$EXEC_LIST"
echo "    восстановлено: $restored, не найдено в целевом дереве: $missing"

echo "[3] Доп. защита: *.sh не из списка (напр. собственные обвязочные скрипты) -> +x ..."
extra=0
while IFS= read -r -d '' f; do
  rel="${f#./}"
  if ! grep -qxF "$rel" "$EXEC_LIST"; then
    chmod +x "$f"
    extra=$((extra+1))
  fi
done < <(find . -name "*.sh" -type f -print0)
echo "    дополнительно помечено +x: $extra"

echo "[OK] Нормализация завершена. Можно запускать tar/genisoimage."
