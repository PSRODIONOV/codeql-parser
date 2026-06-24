/**
 * Точки вставки датчиков динамического анализа (C/C++).
 *
 * Для каждого ФО — позиция тела (после `{`) для датчика входа/выхода.
 * Для каждой ветви (if/else/for/while/do/try, кроме сгенерированных макросами) —
 * позиция начала её блока (после `{`) для датчика ветви.
 *
 * isProjectFile использует ${PROJECT_PATTERN} и исключает операторы — точно
 * так же, как functional_objects.ql, чтобы нумерация ФО совпадала 1:1.
 *
 * Колонки:
 *   kind     — "entry" | "branch"
 *   func     — полное имя ФО (совпадает с Перечень_ФО)
 *   file     — абсолютный путь
 *   ref_line — строка ФО (entry) или строка оператора ветви (branch)
 *   ins_line — строка вставки
 *   ins_col  — колонка вставки (1-based)
 *              has_block=1: колонка `{`; датчик вставляется сразу после него.
 *              ВАЖНО: эта `{` может быть синтезирована макросом (напр.
 *              HotSpot JNI_ENTRY/JVM_ENTRY/JVM_LEAF/UNSAFE_ENTRY и т.п.,
 *              где `{` — часть #define, а не литеральный текст в этой
 *              позиции файла) — в таком случае инструментатор должен сам
 *              проверить символ в файле и использовать end_line/end_col
 *              как запасной якорь (см. has_block=1 ниже).
 *              has_block=0: колонка начала одиночного оператора; нужна обёртка
 *   has_block— 1 если тело в `{...}`, 0 если одиночный оператор
 *   btype    — тип ветви (if/else/else if/for/while/do/try) или "-" для entry
 *   end_line — has_block=0: строка конца одиночного оператора.
 *              has_block=1: строка конца блока/тела (>ins_line, если тело
 *              реально многострочно — надёжный признак того, что `{` была
 *              синтезирована макросом, но дальше идёт литеральный код).
 *   end_col  — колонка последнего символа (включительно) для обоих случаев.
 */
import cpp

predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}") and
  file.getExtension() = ["cpp", "c", "h", "hpp", "cc", "cxx"] and
  not file.getAbsolutePath().matches("%/usr/include%") and
  not file.getAbsolutePath().matches("%/usr/lib%") and
  not file.getAbsolutePath().matches("%/lib/%") and
  not file.getAbsolutePath().matches("%CMakeFiles%")
}

predicate isMacroGeneratedControl(Stmt s) {
  s.(IfStmt).getCondition().isInMacroExpansion()
  or
  s.(WhileStmt).getCondition().isInMacroExpansion()
  or
  s.(ForStmt).getCondition().isInMacroExpansion()
  or
  s.(DoStmt).getCondition().isInMacroExpansion()
  or
  s.(SwitchStmt).getExpr().isInMacroExpansion()
  or
  // for(;;) — условия нет совсем (типичная noreturn-заглушка GLib-макросов,
  // напр. g_error), getCondition() не возвращает результата, поэтому
  // проверка условия выше структурно не может сработать. Только для этого
  // случая проверяем оператор целиком — массовая проверка показала, что для
  // обычных if/while/for/do с условием проверка условия надёжнее проверки
  // всего оператора (~5890 расхождений на реальной базе), переключать общую
  // логику нельзя.
  s instanceof ForStmt and not exists(s.(ForStmt).getCondition()) and s.isInMacroExpansion()
}

/** "case X" или "default" — для btype точки ветви switch. */
string caseBtype(SwitchCase sc) {
  exists(sc.getExpr()) and result = "case"
  or
  not exists(sc.getExpr()) and result = "default"
}

/** Блок-тело ветви, куда ставится датчик (then у if, тело у циклов, try-блок). */
Stmt branchBody(Stmt s) {
  result = s.(IfStmt).getThen()
  or
  result = s.(ForStmt).getStmt()
  or
  result = s.(WhileStmt).getStmt()
  or
  result = s.(DoStmt).getStmt()
  or
  result = s.(TryStmt).getStmt()
}

/** Тело else-ветви (plain else, не else if — else if обрабатывается как IfStmt). */
Stmt elseBody(Stmt s) {
  result = s.(IfStmt).getElse() and
  not result instanceof IfStmt
}

/**
 * else-ветви синтезированы макросом: проверяем условие родительского IfStmt.
 */
predicate isMacroGeneratedElse(Stmt elseStmt) {
  exists(IfStmt parent | parent.getElse() = elseStmt |
    parent.getCondition().isInMacroExpansion()
  )
}

// "else" сюда НЕ входит: эта функция вызывается только для THEN-тела
// (клауза branchBody ниже) — там s остаётся ОДНИМ И ТЕМ ЖЕ IfStmt
// независимо от того, есть ли у него else. Раньше дизъюнкт
// "exists(elseBody(s)) and result = 'else'" добавлял "else" ВТОРЫМ
// результатом для ЛЮБОГО if с else-веткой (CodeQL or — это не if-then-else,
// а "любой верный вариант даёт отдельный результат"), из-за чего probe()
// порождал ДВЕ строки с ОДИНАКОВЫМИ координатами (then-тела) — btype="if"
// И btype="else" — и дедупликация в инструментаторе их не схлопывала
// (btype входит в ключ дедупа), а сам датчик "else" оказывался встроен
// ВНУТРЬ then-блока (там же, где if), а не в реальном else-блоке.
// Настоящая else-точка генерируется отдельной клаузой ниже (elseBody),
// которая хардкодит btype = "else" сама, минуя эту функцию.
string branchType(Stmt s) {
  s instanceof IfStmt   and result = "if"
  or
  s instanceof ForStmt  and result = "for"
  or
  s instanceof WhileStmt and result = "while"
  or
  s instanceof DoStmt   and result = "do"
  or
  s instanceof TryStmt  and result = "try"
}

/** Последний (по тексту) catch-обработчик данного TryStmt. */
predicate isLastHandler(TryStmt t, Handler h) {
  h.getTryStmt() = t and
  not exists(Handler h2 |
    h2.getTryStmt() = t and
    h2.getLocation().getStartLine() > h.getLocation().getStartLine()
  )
}

/**
 * Истинный конец оператора body, оборачиваемого как одиночный (без своих
 * {}) — нужен для закрывающей '}' обёртки датчика (has_block=0). Для
 * большинства Stmt body.getLocation() и есть этот конец. ИСКЛЮЧЕНИЕ —
 * TryStmt без собственных {} вокруг (типичный паттерн без библиотек
 * исключений: `while(...) try { ... } catch(...) { ... }`, без обёртки):
 * CodeQL даёт TryStmt.getLocation() только до конца try-блока, БЕЗ
 * catch-обработчиков, поэтому закрывающая '}' обёртки инструментатором
 * ставилась прямо перед catch — он оставался "осиротевшим" вне фигурных
 * скобок цикла/if, и сборка ломалась (см. rikdataset.cpp, GDAL/RIK).
 * Поэтому для TryStmt берём конец ПОСЛЕДНЕГО catch-блока.
 */
predicate properStmtEnd(Stmt body, int endLine, int endCol) {
  not body instanceof TryStmt and
  endLine = body.getLocation().getEndLine() and
  endCol = body.getLocation().getEndColumn()
  or
  exists(Handler last | isLastHandler(body, last) |
    endLine = last.getBlock().getLocation().getEndLine() and
    endCol = last.getBlock().getLocation().getEndColumn()
  )
}

predicate probe(
  string kind, string func, string file, int refLine,
  int insLine, int insCol, int hasBlock, string btype,
  int endLine, int endCol
) {
  // Точка входа/выхода ФО — тело функции.
  // not isInMacroExpansion(): функции, целиком синтезированные макросом (напр.
  // G_DEFINE_TYPE → get_type/class_intern_init/get_instance_private), у которых
  // нет отдельного места в исходнике — все делят одну строку вызова макроса.
  // not isCompilerGenerated(): неявные (implicit) конструкторы/деструкторы,
  // которые компилятор сам генерирует для класса/шаблона без явного кода —
  // у них тоже нет литерального тела, CodeQL репортит позицию как имя класса
  // (напр. implicit-конструктор шаблона HierarchyVisitor<T> -> позиция
  // "class HierarchyVisitor" — там нет {, только имя класса).
  // Эти же функции исключены из functional_objects.ql (Перечень_ФО), иначе
  // получится N датчиков __TRACE_FN, вставленных в одну и ту же точку файла.
  //
  // file = тело (f.getBlock()), а НЕ f.getFile() — это разные файлы для
  // явных инстанциаций шаблонов вне объявления (типичный HotSpot-паттерн:
  // метод объявлен в .hpp, явная инстанциация написана в ДРУГОМ .cpp).
  // f.getFile() в этом случае указывает на .hpp с объявлением, а
  // insLine/insCol — координаты внутри ДРУГОГО (.cpp) файла; раньше file
  // брался от f.getFile(), а строка/колонка — от тела в другом файле, из-за
  // чего инструментатор искал, например, строку 4555 в 272-строчном .hpp —
  // координаты были корректны, но относились не к тому файлу.
  exists(Function f, File bodyFile |
    f.hasDefinition() and
    exists(f.getBlock()) and
    bodyFile = f.getBlock().getLocation().getFile() and
    isProjectFile(bodyFile) and
    not f.getName().indexOf("operator") = 0 and
    not f.isInMacroExpansion() and
    not f.isCompilerGenerated() and
    // constexpr-функция: __TRACE_FN() вызывает обычную (не constexpr)
    // __trace_enter() — если функция реально вычисляется в constant
    // expression (напр. fmt::v8::monostate::monostate(), is_constant_evaluated()
    // в header-only fmt из osm2pgsql/contrib), такой вызов даёт
    // "call to non-constexpr function" и каскад ошибок по всем зависимым
    // шаблонам. ФО остаётся легитимным в Перечень_ФО, просто без датчика
    // (как самодостаточные макросы/CHECK-идиома) — см. branch-клаузы ниже,
    // там та же причина и тот же fix для __TRACE() внутри ветвей.
    not f.isConstexpr()
  |
    kind    = "entry" and
    func    = f.getQualifiedName() and
    file    = bodyFile.getAbsolutePath() and
    refLine = f.getLocation().getStartLine() and
    insLine = f.getBlock().getLocation().getStartLine() and
    insCol  = f.getBlock().getLocation().getStartColumn() and
    hasBlock = 1 and
    btype   = "-" and
    endLine = f.getBlock().getLocation().getEndLine() and
    endCol  = f.getBlock().getLocation().getEndColumn()
  )
  or
  // Точка ветви — начало её блока или одиночного оператора.
  // not isInMacroExpansion() на enclosing-функции — симметрично с entry-
  // клаузой выше: если ФО целиком исключён из Перечень_ФО как синтезированный
  // макросом, его ветви не должны генерироваться отдельно — иначе lookup по
  // имени функции в Перечень_ФО не находит её (fo_not_found).
  exists(Stmt s, Stmt body |
    s.getEnclosingFunction().hasDefinition() and
    isProjectFile(s.getFile()) and
    not isMacroGeneratedControl(s) and
    not s.getEnclosingFunction().getName().indexOf("operator") = 0 and
    not s.getEnclosingFunction().isCompilerGenerated() and
    not s.getEnclosingFunction().isInMacroExpansion() and
    // см. not f.isConstexpr() в entry-клаузе выше: __TRACE() для ветви —
    // тоже обычная (не constexpr) функция, ломает constexpr enclosing-ФО.
    not s.getEnclosingFunction().isConstexpr() and
    body = branchBody(s)
  |
    kind    = "branch" and
    func    = s.getEnclosingFunction().getQualifiedName() and
    file    = s.getFile().getAbsolutePath() and
    refLine = s.getLocation().getStartLine() and
    insLine = body.getLocation().getStartLine() and
    insCol  = body.getLocation().getStartColumn() and
    btype   = branchType(s) and
    properStmtEnd(body, endLine, endCol) and
    (
      body instanceof BlockStmt and hasBlock = 1
      or
      not body instanceof BlockStmt and hasBlock = 0
    )
  )
  or
  // Точка else-ветви — plain else (не else if, который обрабатывается как IfStmt).
  // elseBody исключает getElse(), возвращающий IfStmt (else if), чтобы не
  // дублировать: else if обрабатывается как обычный IfStmt в клаузе branchBody.
  exists(Stmt parent, Stmt body |
    parent.getEnclosingFunction().hasDefinition() and
    isProjectFile(parent.getFile()) and
    not isMacroGeneratedElse(body) and
    not isMacroGeneratedControl(parent) and
    not parent.getEnclosingFunction().getName().indexOf("operator") = 0 and
    not parent.getEnclosingFunction().isCompilerGenerated() and
    not parent.getEnclosingFunction().isInMacroExpansion() and
    not parent.getEnclosingFunction().isConstexpr() and
    body = elseBody(parent)
  |
    kind    = "branch" and
    func    = parent.getEnclosingFunction().getQualifiedName() and
    file    = parent.getFile().getAbsolutePath() and
    refLine = parent.getLocation().getStartLine() and
    insLine = body.getLocation().getStartLine() and
    insCol  = body.getLocation().getStartColumn() and
    btype   = "else" and
    properStmtEnd(body, endLine, endCol) and
    (
      body instanceof BlockStmt and hasBlock = 1
      or
      not body instanceof BlockStmt and hasBlock = 0
    )
  )
  or
  // Точка ветви switch — case/default. В отличие от if/for/while/do/try,
  // у каждой case-метки НЕТ своих {} — все метки делят ОДИН общий блок
  // тела switch, поэтому ни "поиск {", ни обёртка "{ датчик; оператор; }"
  // (как для has_block=0) здесь не подходят: после метки просто следует
  // обычная последовательность операторов. hasBlock=2 — отдельный, третий
  // вид для инструментатора: вставить текст датчика ПРЯМО после ':'
  // метки, без какой-либо обёртки в скобки.
  exists(SwitchStmt sw, SwitchCase sc |
    sc.getSwitchStmt() = sw and
    sw.getEnclosingFunction().hasDefinition() and
    isProjectFile(sc.getFile()) and
    not isMacroGeneratedControl(sw) and
    not sw.getEnclosingFunction().getName().indexOf("operator") = 0 and
    not sw.getEnclosingFunction().isCompilerGenerated() and
    not sw.getEnclosingFunction().isInMacroExpansion() and
    not sw.getEnclosingFunction().isConstexpr() and
    // Сама МЕТКА может быть синтезирована макросом, даже если switch и
    // функция — нет (см. REP8/REP16 в assembler_x86.cpp: один макровызов
    // `case REP8(0xB8):` разворачивается в 8 НЕЗАВИСИМЫХ case-меток
    // `case (0xB8)+0: case (0xB8)+1: ... case (0xB8)+7:`, физически
    // занимающих одно и то же место в исходнике). У всех таких меток
    // getLocation() указывает на ОДНО И ТО ЖЕ (или перекрывающееся) место
    // вызова макроса — надёжного отдельного места для датчика КАЖДОЙ из
    // них нет (несколько вставок на одну позицию ломают друг друга, как
    // вставки сразу до и после общего ':'). Пропускаем такие метки.
    not sc.isInMacroExpansion() and
    (exists(sc.getExpr()) implies not sc.getExpr().isInMacroExpansion())
  |
    kind    = "branch" and
    func    = sw.getEnclosingFunction().getQualifiedName() and
    file    = sc.getFile().getAbsolutePath() and
    // refLine — строка САМОЙ метки case/default (а не switch): по ней
    // инструментатор ищет номер ветви в Перечень_ветвей (где каждая метка —
    // отдельная строка). Раньше тут была строка switch, и ВСЕ метки получали
    // номер первой ветви (br=1) — см. weekday_kind в test-project-cpp-branches.
    refLine = sc.getLocation().getStartLine() and
    insLine = sc.getLocation().getEndLine() and
    insCol  = sc.getLocation().getEndColumn() + 1 and
    hasBlock = 2 and
    btype   = caseBtype(sc) and
    endLine = sc.getLocation().getEndLine() and
    endCol  = sc.getLocation().getEndColumn()
  )
  or
  // Точка ветви catch — тело catch-блока уже целиком в {} (как у try),
  // поэтому используется ТОТ ЖЕ hasBlock=1 механизм поиска { в
  // инструментаторе, никакого нового вида не нужно.
  exists(TryStmt t, Handler h |
    h.getTryStmt() = t and
    h.getEnclosingFunction().hasDefinition() and
    isProjectFile(h.getFile()) and
    not h.getEnclosingFunction().getName().indexOf("operator") = 0 and
    not h.getEnclosingFunction().isCompilerGenerated() and
    not h.getEnclosingFunction().isInMacroExpansion() and
    not h.getEnclosingFunction().isConstexpr()
  |
    kind    = "branch" and
    func    = h.getEnclosingFunction().getQualifiedName() and
    file    = h.getFile().getAbsolutePath() and
    refLine = t.getLocation().getStartLine() and
    insLine = h.getBlock().getLocation().getStartLine() and
    insCol  = h.getBlock().getLocation().getStartColumn() and
    hasBlock = 1 and
    btype   = "catch" and
    endLine = h.getBlock().getLocation().getEndLine() and
    endCol  = h.getBlock().getLocation().getEndColumn()
  )
}

from string kind, string func, string file, int refLine,
     int insLine, int insCol, int hasBlock, string btype,
     int endLine, int endCol
where probe(kind, func, file, refLine, insLine, insCol, hasBlock, btype, endLine, endCol)
// as-алиасы (snake_case) — чтобы при сборе в составе сырых данных (раздел
// "probe" в project.db) заголовки CSV совпадали со схемой RAW_SCHEMA["q_probe"]
// и инструментатор читал геометрию из project.db БЕЗ отдельного запроса.
// Порядок колонок не меняется — позиционный парсинг (fallback в instrument_cpp.py)
// продолжает работать.
select kind, func, file, refLine as ref_line,
       insLine as ins_line, insCol as ins_col, hasBlock as has_block,
       btype, endLine as end_line, endCol as end_col
order by file, ins_line, ins_col
