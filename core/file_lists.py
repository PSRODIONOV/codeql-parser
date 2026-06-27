#!/usr/bin/env python3
"""Белый/чёрный список файлов — единый для статического анализа
(core/project_runner.py) и для извлечения исходников из src.zip БД для
инструментации (dynamic/instrument_c_make.py, dynamic/instrument_cpp.py).

Формат: простой текстовый файл, один путь на строку (относительный или
абсолютный — в любом стиле слешей), пустые строки и строки, начинающиеся
с '#', игнорируются.

Один и тот же список применяется к обеим стадиям, чтобы инструментатор
гарантированно видел те же файлы, что и статический анализ — раньше
несогласованность двух параллельных реализаций фильтрации уже приводила
к багам (см. историю фиксов с functional_objects.ql/probe_points.ql).
"""
from pathlib import Path


def read_file_list(path) -> list:
    """Читает текстовый список путей, по одному на строку."""
    result = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            result.append(line)
    return result


def _norm(p: str) -> str:
    return p.replace("\\", "/").rstrip("/")


def path_matches_list(actual_path: str, list_entries: list) -> bool:
    """True если actual_path (как в данных CodeQL — обычно абсолютный путь
    build-машины, возможно без ведущего '/' — напр. внутренние имена
    src.zip) соответствует одной из записей списка.

    Сравнение всегда идёт без учёта ведущего '/' с обеих сторон, поэтому
    результат одинаков независимо от того, передан ли actual_path как
    абсолютный (CodeQL getAbsolutePath()) или как внутреннее имя ZIP-записи
    (без ведущего слеша).

    Запись списка может быть:
      - точным путём build-машины (как показан в отчётах, напр. в колонке
        "Объявлен в" Перечень_ФО.csv) — сравнение точное;
      - относительным путём (напр. 'hotspot/src/share/vm/oops/Foo.cpp') —
        совпадение по ОКОНЧАНИЮ пути (хвосту), на границе '/'.

    Произвольные абсолютные пути с ДРУГОЙ машины/диска (напр. путь на
    диске пользователя, не совпадающий с build-путём CodeQL) надёжно не
    сопоставить без знания соответствия префиксов — используйте
    относительный путь (хвост от каталога пакета) в таких случаях.
    """
    actual = _norm(actual_path).lstrip("/")
    for raw in list_entries:
        e = _norm(raw).lstrip("/")
        if not e:
            continue
        if actual == e:
            return True
        if actual.endswith("/" + e):
            return True
    return False


def path_matches_patterns(path: str, patterns: list) -> bool:
    """Путь подходит хотя бы под один glob-шаблон (fnmatch, без учёта
    регистра; без '*'/'?' трактуется как подстрока для удобства).

    Перенесено из core/project_runner.py (было _path_matches) — единый
    модуль для всех видов фильтрации путей (шаблоны И списки), чтобы
    extract_project_sources (инструментация) и apply_file_filters
    (статика) комбинировали include/exclude ОДИНАКОВО: раньше extract_*
    требовал совпадения И с --pattern, И со списком одновременно (AND),
    а apply_file_filters — совпадения с шаблоном ИЛИ со списком (OR);
    из-за этого нечего не совпадало, если белое поле в GUI содержало
    glob-шаблоны (напр. '*/src/*') — path_matches_list их не понимает.

    Сравнение нечувствительно к наличию ведущего '/' — шаблоны обычно
    вводятся/хранятся в формате CodeQL getAbsolutePath() (с ведущим '/',
    напр. '/tmp/java_build*'), а путь может прийти и без него (напр.
    внутреннее имя ZIP-записи в src.zip) — без этой нормализации шаблон
    с ведущим '/' никогда не совпал бы с путём без него, и наоборот."""
    import fnmatch
    p = "/" + path.replace("\\", "/").lower().lstrip("/")
    for pat in patterns:
        pat = "/" + pat.strip().replace("\\", "/").lower().lstrip("/")
        if pat == "/":
            continue
        if "*" not in pat and "?" not in pat:
            if pat in p:
                return True
        elif fnmatch.fnmatch(p, pat) or fnmatch.fnmatch(p, "*" + pat + "*"):
            return True
    return False


def sensor_filter_factory(include_patterns=None, exclude_patterns=None, counters=None):
    """Пользовательский белый/чёрный список ВСТАВКИ ДАТЧИКОВ (см.
    ProjectDB.set_sensor_filters, вкладка «Динамический анализ») — заменяет
    жёстко заданные в коде исключения (напр. для пакетов раннего bootstrap
    JVM — java/lang/**, java/util/concurrent/** — см. историю
    instrument_java.py), чтобы не нужно было править сам инструментатор под
    каждый новый проект. Применяется ПОСЛЕ базового --pattern/include-list/
    exclude-list (общая область проекта, та же, что у статики) — сужает или
    дополнительно исключает файлы, в которые вставляются датчики. Пусто =
    не ограничивает (семантика как у path_matches_patterns).

    counters (опционально) — dict, в который ПОПОЛНЯЮТСЯ (а не
    перезаписываются) счётчики "excluded" (попал под чёрный список) и
    "not_in_whitelist" (не подошёл белому списку), чтобы вызывающий код
    мог сообщить в лог, сколько файлов реально затронули списки — без
    этого видно только общий "отфильтровано: N" от extract_project_sources,
    куда сваливаются ВСЕ причины пропуска файла без разбора."""
    def check(zip_path: str) -> bool:
        if exclude_patterns and path_matches_patterns(zip_path, exclude_patterns):
            if counters is not None:
                counters["excluded"] = counters.get("excluded", 0) + 1
            return False
        if include_patterns and not path_matches_patterns(zip_path, include_patterns):
            if counters is not None:
                counters["not_in_whitelist"] = counters.get("not_in_whitelist", 0) + 1
            return False
        return True
    return check


def is_generated_path(path: str) -> bool:
    """Эвристика: файл — артефакт, появляющийся только во время сборки
    (ADLC/JVMTI/JFR-генераторы и т.п.), а не часть исходников, написанных
    разработчиком. Используется только для информационного предупреждения
    в логе — не влияет на сами фильтры include/exclude."""
    norm = "/" + _norm(path).lstrip("/")
    return "/build/" in norm or "/generated/" in norm


# src.zip — это снэпшот ВСЕГО, что прочитал компилятор, включая системные
# заголовки (/usr/include, /usr/lib/gcc/.../include-fixed, JVM-заголовки и
# т.п.) — они лежат под СОВСЕМ другим корнем (напр. 'usr/...'), чем сам
# проект (напр. 'tmp/java_build.XXX/...'). Эти файлы не часть проекта и не
# должны ни извлекаться, ни участвовать в подсчёте общего префикса —
# иначе единого префикса не находится вообще (нет common ancestor между
# 'tmp/...' и 'usr/...').
_SYSTEM_PATH_MARKERS = ("usr/include/", "usr/lib/", "lib/x86_64", "usr/lib/jvm/")


def is_system_path(path: str) -> bool:
    """Системный заголовок/библиотека (см. _SYSTEM_PATH_MARKERS) — не часть
    анализируемого проекта, исключается из извлечения безусловно."""
    norm = _norm(path).lstrip("/")
    return norm.startswith(_SYSTEM_PATH_MARKERS) or "/usr/include/" in ("/" + norm)


def detect_db_prefix(zip_path) -> str:
    """Определяет общий префикс build-машины среди ПРОЕКТНЫХ путей src.zip
    (напр. 'tmp/java_build.VJWGjn/'), чтобы извлекаемая структура каталогов
    начиналась от имени пакета проекта, а не от служебного временного
    пути сборки. Системные файлы (is_system_path) не учитываются — иначе
    общего префикса не найдётся вовсе (разные корни 'tmp/' и 'usr/').
    Без ведущего и с одним хвостовым '/' (или '' если общего префикса нет)."""
    import posixpath
    import zipfile as _zipfile
    with _zipfile.ZipFile(zip_path) as z:
        names = [n.replace("\\", "/").lstrip("/") for n in z.namelist()
                if not n.endswith("/") and not is_system_path(n)]
    if not names:
        return ""
    try:
        common = posixpath.commonpath(names)
    except ValueError:
        return ""
    if not common or common == ".":
        return ""
    return common.rstrip("/") + "/"


def extract_project_sources(db_path, dest_dir, pattern_filter=None,
                            include_patterns=None, exclude_patterns=None,
                            include_list=None, exclude_list=None,
                            log=None) -> dict:
    """Извлекает дерево исходников прямо из src.zip внутри CodeQL БД —
    точный снэпшот того, что реально анализировал CodeQL, включая файлы,
    появляющиеся только во время сборки (ADLC/JVMTI/JFR и т.п.), которых
    нет на диске до сборки (см. историю: 23589 из 23778 пропущенных точек
    вставки датчиков объяснялись именно отсутствием таких файлов в
    переданном пользователем --project). Заменяет необходимость передавать
    отдельный каталог-копию исходников в instrument_c_make.py/instrument_cpp.py
    — каталог для инструментации теперь всегда есть в самой БД.

    pattern_filter — БАЗОВЫЙ фильтр принадлежности проекту (напр. обёртка
    над --pattern для CodeQL/isProjectFile, различающим пакеты в одной БД)
    — применяется ВСЕГДА (AND), если задан.
    include_patterns/exclude_patterns (glob/подстрока, см.
    path_matches_patterns) И include_list/exclude_list (точные/относительные
    пути, см. path_matches_list) — это ОДНА группа "пользовательского"
    отбора подмножества файлов В ПРЕДЕЛАХ проекта: совпадение с ЛЮБЫМ из
    них (шаблон ИЛИ список) достаточно для включения (OR) — та же
    семантика, что в apply_file_filters (core/project_runner.py), чтобы
    статика и инструментация были согласованы при одинаковых настройках.

    Возвращает {'prefix', 'extracted', 'skipped_filtered', 'generated_skipped'}.
    """
    import zipfile as _zipfile
    db_path = Path(db_path)
    src_zip = db_path / "src.zip"
    if not src_zip.exists():
        raise FileNotFoundError(f"Не найден src.zip в БД: {src_zip}")
    dest_dir = Path(dest_dir)

    prefix = detect_db_prefix(str(src_zip))

    def file_ok(zip_path: str) -> bool:
        if pattern_filter and not pattern_filter(zip_path):
            return False
        if include_patterns or include_list:
            ok = (include_patterns and path_matches_patterns(zip_path, include_patterns)) or \
                 (include_list and path_matches_list(zip_path, include_list))
            if not ok:
                return False
        if exclude_patterns and path_matches_patterns(zip_path, exclude_patterns):
            return False
        if exclude_list and path_matches_list(zip_path, exclude_list):
            return False
        return True

    extracted = 0
    skipped_filtered = 0
    generated_skipped = 0
    with _zipfile.ZipFile(src_zip) as z:
        for name in z.namelist():
            if name.endswith("/"):
                continue
            norm = name.replace("\\", "/").lstrip("/")
            if is_system_path(norm):
                continue
            if not file_ok(norm):
                skipped_filtered += 1
                if is_generated_path(norm):
                    generated_skipped += 1
                continue
            rel = norm[len(prefix):] if prefix and norm.startswith(prefix) else norm
            target = dest_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                data = z.read(name)
            except Exception as e:
                if log:
                    log(f"[extract] ошибка чтения {name}: {e}")
                continue
            target.write_bytes(data)
            extracted += 1

    if log:
        log(f"[extract] Извлечено из src.zip: {extracted} файлов "
            f"(отфильтровано: {skipped_filtered}, из них сгенерированных: {generated_skipped})")
    return {"prefix": prefix, "extracted": extracted,
            "skipped_filtered": skipped_filtered, "generated_skipped": generated_skipped}
