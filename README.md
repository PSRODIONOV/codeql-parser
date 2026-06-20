# CodeQL Database Analyzer

## Описание

Программа принимает на вход базу данных CodeQL и строит набор CSV-отчётов, содержащих:

1. **Перечень функциональных объектов (ФО)** — методы класса, функции, процедуры, конструкторы, деструкторы, точки входа.
2. **Перечень избыточных функциональных объектов** — объявлены, но не вызываются в коде.
3. **Перечень информационных объектов (ИО)** — переменные, константы, параметры функций, локальные/глобальные переменные, поля классов/структур, статические переменные и поля.
4. **Перечень избыточных информационных объектов** — объявлены, но не используются в коде.
5. **Матрицу связей по управлению** — квадратная матрица ФО×ФО, в пересечении — количество вызовов.
6. **Матрицу связей по информации** — квадратная матрица ФО×ФО, в пересечении — номера ИО, которые связывают соответствующие ФО.

## Структура проекта

```
.
├── third-party/             # ВСЕ заимствования (тулчейны/рантаймы/vendored) [не в git]
│   ├── codeql-win/          #   CodeQL CLI (Windows)
│   ├── codeql-linux/        #   CodeQL CLI (Linux)
│   ├── jdk25-win/  jdk25-linux/   #   JDK (для Java/Joern)
│   ├── apache-maven-3.9.6/  #   Maven (сборка Java-проектов)
│   ├── nodejs/  node_modules/     #   Node.js + elkjs (раскладка блок-схем)
│   ├── php-8.3/  joern-cli/  #   PHP-рантайм + Joern (анализ PHP)
│   ├── python-packages/     #   vendored Pillow
│   ├── drakonhub_desktop/   #   заимствованный просмотрщик DRAKON
│   └── ogdf/                #   библиотека OGDF (графовая раскладка)
├── paths.py                 # Центральный резолвер: корень + third_party(...)
├── core/                    # Анализ: запуск запросов, БД, пайплайн, отчёты
│   ├── codeql_analyzer.py  joern_analyzer.py  sql_analyzer.py
│   ├── report_generator.py  project_db.py  project_runner.py
├── viz/                     # Визуализация: блок-схемы и графы
│   ├── flowchart_generator.py  elk_generator.py  drakon_generator.py
│   ├── axis_layout.py  graph_builder.py  func_key.py
│   └── elk_layout.js        #   раскладка ELK (Node)
├── gui/                     # Графический интерфейс (PyQt5)
│   └── gui_project.py  gui_widgets.py  gui_styles.py
├── queries/                 # QL-запросы по языкам (cpp/java/javascript/python)
├── dynamic/                 # Динамический анализ (датчики/трассы/покрытие)
│   ├── instrument_*.py      #   инструментаторы по языкам + instrument_c_make.py
│   ├── coverage_report.py  analyze_project.py
│   ├── runtime/  drivers/   #   рантаймы датчиков + примеры драйверов
│   └── README.md            #   ПОДРОБНАЯ инструкция по динамике
├── tests/                   # Регрессионные pytest-тесты (4 языка + project_db)
├── examples/                # Тест-проекты, БД, эталонные отчёты      [не в git]
├── native/                  # ogdf_layout.cpp — обвязка OGDF (C++)
├── scripts/                 # Разовые dev-скрипты
├── data/                    # Разовые входные данные (не в git)
├── main.py                  # CLI статического анализа (точка входа)
├── run_project_gui.py       # Запуск GUI (точка входа)
├── regen_drakon.py          # Перегенерация DRAKON-схем (утилита)
├── requirements.txt  requirements_gui.txt  package.json
├── GUI_README.md
└── README.md
```

> Каталог `third-party/` (все заимствования) и `examples/` в git и в архив
> программы не входят — докачиваются отдельно (см. ниже). Любой модуль
> обращается к заимствованиям только через `paths.third_party(...)`.

## Требования

Программа поддерживает 4 языка анализа: **C++, Java, JavaScript, Python**.

| Компонент | Назначение | Поставка |
|-----------|-----------|----------|
| **Python** 3.8+ | основные скрипты | системный |
| **CodeQL CLI** | создание БД и запуск запросов | в комплекте (`third-party/codeql-win/`, `third-party/codeql-linux/`) |
| **CodeQL query packs** | `codeql/{cpp,java,javascript,python}-all` | ⚠️ докачиваются (см. развёртывание) |
| **Node.js + elkjs** | раскладка/рендеринг блок-схем | в комплекте (`third-party/nodejs/`, `third-party/node_modules/`) |
| **Pillow** | генерация изображений | в комплекте (`third-party/python-packages/`) |
| **Maven + JDK 11+** | сборка Java-проектов | Maven в комплекте; JDK берётся из поставки CodeQL |
| **C++ компилятор** (g++/clang/MSVC) | сборка C++-проектов | ⚠️ системный, не входит в комплект |
| **PyQt5, PyQtWebEngine** | GUI (опционально) | ⚠️ докачиваются (`requirements_gui.txt`) |

> Для анализа уже готовой БД CodeQL компилятор/Maven не нужны — они требуются только для **создания** БД из исходников соответствующего языка.

## Развёртывание на новой ЭВМ

Каталог `third-party/` (CodeQL, JDK, Maven, Node.js+elkjs, PHP, Joern, Pillow,
OGDF, drakonhub) входит в комплект и работает офлайн. **Однако две группы
зависимостей в комплект не входят и требуют докачки (нужен интернет):**

### 1. Query packs CodeQL (обязательно)

Библиотеки `codeql/<язык>-all` хранятся в `~/.codeql/packages` (вне проекта) и при
переносе на другую машину отсутствуют. Без них запросы не скомпилируются с ошибкой
`Pack 'codeql/<язык>-all' was not found`. Установить для нужных языков:

```bash
# Windows (из корня проекта)
third-party\codeql-win\codeql.exe pack install queries\cpp
third-party\codeql-win\codeql.exe pack install queries\java
third-party\codeql-win\codeql.exe pack install queries\javascript
third-party\codeql-win\codeql.exe pack install queries\python

# Linux / macOS
third-party/codeql-linux/codeql pack install queries/cpp
third-party/codeql-linux/codeql pack install queries/java
third-party/codeql-linux/codeql pack install queries/javascript
third-party/codeql-linux/codeql pack install queries/python
```

Версии зафиксированы в `queries/<язык>/codeql-pack.lock.yml` — установка
воспроизводимая.

### 2. PyQt5 для GUI (только если нужен графический интерфейс)

CLI (`main.py`) работает без PyQt5. Для `run_project_gui.py` нужно доустановить:

```bash
pip install -r requirements_gui.txt
# или локально, по аналогии с остальными пакетами:
pip install --target=third-party/python-packages -r requirements_gui.txt
```

### 3. Компилятор для создания C++-баз (если будете строить C++ БД)

C++-компилятор в комплект не входит. Установить системно:

```bash
# Linux
sudo apt-get update && sudo apt-get install -y g++ build-essential
# Windows — MSVC Build Tools, MinGW или Strawberry Perl (g++)
```

## Установка (Python-зависимости CLI)

```bash
pip install --target=third-party/python-packages -r requirements.txt
```

Уже выполнено — Pillow лежит в `third-party/python-packages/`. Прочие зависимости CLI —
стандартная библиотека Python.

## Создание БД CodeQL

БД создаётся напрямую через CodeQL CLI. Команда зависит от языка: для C++/Java
указывается `--command` со сборкой, для JavaScript/Python — сборка не нужна.

```bash
CODEQL=third-party/codeql-win/codeql.exe   # или third-party/codeql-linux/codeql

# Python / JavaScript — без сборки
$CODEQL database create databases/small-projects/test-project-python-db \
  --language=python \
  --source-root=test-projects/small-projects/test-project-python --overwrite

# C++ — со сборкой компилятором
$CODEQL database create databases/small-projects/test-project-cpp-db \
  --language=cpp --source-root=test-projects/small-projects/test-project-cpp \
  --command="g++ -std=c++14 -I. *.cpp -o app" --overwrite

# Java — со сборкой (JDK из поставки CodeQL + Maven из apache-maven-3.9.6/)
$CODEQL database create databases/small-projects/test-project-java-db \
  --language=java --source-root=test-projects/small-projects/test-project-java \
  --command="javac -encoding UTF-8 *.java" --overwrite
```

> Перед первым запуском на новой машине выполните `codeql pack install` для нужных
> языков (см. раздел «Развёртывание на новой ЭВМ»).

## Запуск анализатора

```bash
python main.py <путь-к-БД> -o <выходная-папка> --language <язык>
```

Пример:

```bash
python main.py databases/small-projects/test-project-python-db \
  -o reports/small-projects/python --language python --codeql third-party/codeql-win/codeql.exe
```

Параметры:
- `db_path` — путь к директории с БД CodeQL.
- `-o, --output` — директория для отчётов.
- `--language` — `cpp` | `java` | `javascript` | `python`.
- `--codeql` — путь к исполняемому файлу `codeql` (если не в PATH).
- `--pattern` — маска пути исходников для фильтрации (например `%small-projects/test-project-python%`).
- `--ram` — верхний предел памяти (МБ) на запрос CodeQL (по умолчанию 4096).
- `--max-routes` — верхняя страховочная отсечка числа маршрутов на ФО
  (по умолчанию 1000). Маршруты строятся как **базисный (цикломатически
  независимый) набор** по числу ветвлений: V(G) = (число ветвлений)+1, покрывающий
  каждую ветвь хотя бы одним маршрутом (соответствует РД НДВ №114 — «перечень
  маршрутов выполнения ФО (ветвей)»). Полный экспоненциальный перебор путей (2^N)
  не выполняется, поэтому отсечка на практике не достигается.

## Проектный графический интерфейс (рекомендуется)

Проектно-ориентированный GUI хранит все сведения анализа в SQLite (`project.db`),
поэтому к проекту можно возвращаться — отчёты создаются из базы без повторного
прогона CodeQL.

```powershell
$env:_JAVA_OPTIONS=""        # снять лимит памяти JVM
python run_project_gui.py
```

Возможности: создание/открытие проектов с историей, статический анализ → БД,
создание отчётов из БД, динамический анализ (инструментация + покрытие), фильтры
файлов (бел./чёрный списки), тайминги и прогресс-бар в логах. Подробно —
[GUI_README.md](GUI_README.md).

**Архитектура персистентности:** `project_runner.run_static_analysis` выполняет
запросы CodeQL и тяжёлые вычисления (ELK/маршруты) один раз и складывает сырые +
производные данные в `project.db`; `generate_static_reports` — быстрый дамп из базы
в `reports/static`. Повторное создание отчётов не запускает CodeQL/ELK.

## Регрессионные тесты

После изменений в запросах/генераторах прогоните тесты — они сверяют отчёты и
блок-схемы эталонных мелких проектов с исходными текстами, плюс round-trip
персистентности (`project_db`):

```bash
cd tests && python -m pytest . -v
```

## Пример вывода

```
Database: test-project-db
Output:   reports
CodeQL:   codeql
--------------------------------------------------
[1/6] Collecting functional objects...
       Found: 42 objects
       Saved: reports\Перечень_ФО.csv
[2/6] Collecting redundant (unused) functional objects...
       Found: 3 objects
       Saved: reports\Перечень_избыточных_ФО.csv
[3/6] Collecting informational objects...
       Found: 67 objects
       Saved: reports\Перечень_ИО.csv
[4/6] Collecting redundant (unused) informational objects...
       Found: 5 objects
       Saved: reports\Перечень_избыточных_ИО.csv
[5/6] Building control-flow matrix...
       Found: 35 relations
       Saved: reports\Матрица_связей_по_управлению.csv
[6/6] Building data-flow matrix...
       Found: 128 relations
       Saved: reports\Матрица_связей_по_информации.csv
--------------------------------------------------
Done!
```

## Структура отчётов

| Файл | Содержимое |
|------|-----------|
| `Перечень_ФО(процедур_функций).csv` | № п/п, Объект, Объявлен в, Число использований |
| `Использования_ФО(процедур_функций).csv` | № ФО, Объект, Используется в, Вызывается объектом |
| `Перечень_избыточных_ФО(процедур_функций).csv` | № п/п, Избыточный объект, Объявлен в |
| `Перечень_ИО.csv` | № п/п, Объект, Объявлен в, Тип объекта, Число использований |
| `Использования_ИО.csv` | № ИО, Объект, Используется в, Тип использования, Вызывается объектом |
| `Перечень_избыточных_ИО.csv` | № п/п, Избыточный объект, Объявлен в |
| `Матрица_связей_по_управлению.csv` | Квадратная матрица ФО×ФО, на пересечении — количество вызовов |
| `Матрица_связей_по_информации.csv` | Квадратная матрица ФО×ФО, на пересечении — номера ИО |

## Динамический анализ (датчики · трассы · покрытие)

Дополняет статику: встраивает датчики в копию исходников, собирает трассы выполнения
и строит отчёты о **динамическом покрытии** ФО и ветвей (номера совпадают со статикой 1:1).

Краткий цикл:
1. **Статика** → `reports/static` (с `Перечень_ветвей.csv`).
2. **Инструментация** (`dynamic/instrument_<lang>.py`) → `instrumented-sources` + `Карта_датчиков.csv`.
3. **Сборка и запуск** инструментированного кода → трассы `$HOME/<lang>-<ts>-<pid>.log`.
4. **Покрытие** (`dynamic/coverage_report.py`) → `reports/dynamic`.

Поддержаны все 4 языка (C/C++, Python, JavaScript, Java), включая проекты со своей
сборкой (make/Maven). В GUI — группа «🔬 ДИНАМИЧЕСКИЙ АНАЛИЗ» (кнопки «Инструментировать»
и «Построить покрытие»).

**Полная инструкция, варианты по языкам и описание доп. аргументов — в
[`dynamic/README.md`](dynamic/README.md).**

## Примечания

- Деструкторы и `main` исключены из списка избыточных ФО, так как они имеют особые правила вызова.
- Матрица управления строится на основе явных вызовов функций (`FunctionCall`).
- Матрица информации строится на основе доступа к переменным (`VariableAccess`) внутри функций: если два ФО используют один ИО, в соответствующей ячейке ставится номер этого ИО из `Перечень_ИО.csv`.
