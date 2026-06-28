import cpp

/** Файл принадлежит тестовому проекту */
predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}") and
  file.getExtension() = ["cpp", "c", "h", "hpp"] and not file.getAbsolutePath().matches("%CMakeFiles%") and not file.getAbsolutePath().matches("%/usr/include%") and not file.getAbsolutePath().matches("%/usr/lib%") and not file.getAbsolutePath().matches("%/lib/%") and not file.getAbsolutePath().matches("%.moc%") and not file.getAbsolutePath().matches("%.rcc%") and not file.getAbsolutePath().matches("%.ui%") and not file.getAbsolutePath().matches("%.._._%")
}

/**
 * Управляющая конструкция, СГЕНЕРИРОВАННАЯ макросом (её нет в исходных текстах).
 * Например, ngx_log_error(...) разворачивается в
 *   if ((log)->log_level >= level) ngx_log_error_core(...)
 * — этот if не виден в коде пользователя и не должен попадать в блок-схему/граф.
 *
 * Отличаем по условию: у такого if/while/for/do само УСЛОВИЕ целиком из тела
 * макроса (isInMacroExpansion). У реального условия оператор сравнения написан
 * пользователем, даже если в нём используется макрос-константа (NULL, NGX_OK).
 */
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

/** "case X" или "default" — для метки/типа case-точки switch. */
predicate isDefaultCase(SwitchCase sc) { not exists(sc.getExpr()) }

/** Тип оператора (ровно одно значение для отобранных операторов) */
string getStmtType(Stmt s) {
  s instanceof IfStmt and result = "if"
  or
  s instanceof WhileStmt and result = "while"
  or
  s instanceof ForStmt and result = "for"
  or
  s instanceof DoStmt and result = "do"
  or
  s instanceof ReturnStmt and result = "return"
  or
  s instanceof TryStmt and result = "try"
  or
  s instanceof SwitchStmt and result = "switch"
  or
  // case/default — НЕ собственный узел блок-схемы (как и else), а метка
  // границы ветви switch; см. _build_hierarchy/_render_node — case-строки
  // используются только для партиционирования и текста на ребре.
  s instanceof SwitchCase and isDefaultCase(s) and result = "default"
  or
  s instanceof SwitchCase and not isDefaultCase(s) and result = "case"
  or
  s instanceof BreakStmt and result = "break"
  or
  s instanceof ContinueStmt and result = "continue"
  or
  s instanceof GotoStmt and result = "goto"
  or
  s instanceof LabelStmt and result = "label"
  or
  // throw expr; — ExprStmt, внутри которого ThrowExpr; выделяем в отдельный тип
  s instanceof ExprStmt and s.(ExprStmt).getExpr() instanceof ThrowExpr and result = "throw"
  or
  s instanceof ExprStmt and not s.(ExprStmt).getExpr() instanceof ThrowExpr and result = "expr"
}

/** Читаемая метка оператора (ровно одно значение) */
string getStmtLabel(Stmt s) {
  exists(IfStmt ifs | ifs = s | result = "if (" + ifs.getCondition().toString() + ")")
  or
  exists(WhileStmt ws | ws = s | result = "while (" + ws.getCondition().toString() + ")")
  or
  s instanceof ForStmt and result = "for (...)"
  or
  exists(DoStmt ds | ds = s | result = "do ... while (" + ds.getCondition().toString() + ")")
  or
  exists(ReturnStmt rs | rs = s |
    if exists(rs.getExpr())
    then result = "return " + rs.getExpr().toString()
    else result = "return"
  )
  or
  s instanceof TryStmt and result = "try"
  or
  exists(SwitchStmt sw | sw = s | result = "switch (" + sw.getExpr().toString() + ")")
  or
  exists(SwitchCase sc | sc = s and not isDefaultCase(sc) | result = "case " + sc.getExpr().toString())
  or
  s instanceof SwitchCase and isDefaultCase(s) and result = "default"
  or
  s instanceof BreakStmt and result = "break"
  or
  s instanceof ContinueStmt and result = "continue"
  or
  exists(GotoStmt g | g = s | result = "goto " + g.getName())
  or
  exists(LabelStmt l | l = s | result = l.getName())
  or
  exists(ExprStmt es, ThrowExpr te | es = s and te = es.getExpr() |
    if exists(te.getExpr())
    then result = "throw " + te.getExpr().toString()
    else result = "throw"
  )
  or
  s instanceof ExprStmt and not s.(ExprStmt).getExpr() instanceof ThrowExpr and result = s.toString()
}

// ПРИМ.: else-if (IfStmt в позиции else) репортится КАК else-ветка родителя
// (else_line указывает на строку вложенного if) — это нужно перечислителю
// маршрутов (_arms делит детей на «да»/«нет» по else_line, иначе вложенный if
// попадёт в «да»-рукав и «нет»-маршрут не построится). Фантомная "else"-запись
// в инвентаре при этом НЕ создаётся: синтез else в flowchart_generator
// пропускает случай, когда else_line совпадает со строкой вложенного if
// (там уже есть отдельная if-ветвь else-if).

/** Строка начала else/catch-ветки, иначе 0 */
int getElseLine(Stmt s) {
  s instanceof IfStmt and exists(s.(IfStmt).getElse()) and
  result = s.(IfStmt).getElse().getLocation().getStartLine()
  or
  s instanceof TryStmt and
  result = min(Handler h | h.getTryStmt() = s | h.getLocation().getStartLine())
  or
  not (s instanceof IfStmt and exists(s.(IfStmt).getElse())) and
  not s instanceof TryStmt and
  result = 0
}

/** Строка конца else-ветки, иначе 0 */
int getElseLineEnd(Stmt s) {
  s instanceof IfStmt and exists(s.(IfStmt).getElse()) and
  result = s.(IfStmt).getElse().getLocation().getEndLine()
  or
  not (s instanceof IfStmt and exists(s.(IfStmt).getElse())) and
  result = 0
}

/** else-ветва в { } (1) или одиночный оператор (0), иначе 0 */
int getElseHasBlock(Stmt s) {
  s instanceof IfStmt and exists(s.(IfStmt).getElse()) and
  s.(IfStmt).getElse() instanceof BlockStmt and
  result = 1
  or
  s instanceof IfStmt and exists(s.(IfStmt).getElse()) and
  not s.(IfStmt).getElse() instanceof BlockStmt and
  result = 0
  or
  not (s instanceof IfStmt and exists(s.(IfStmt).getElse())) and
  result = 0
}

// ── Геометрия вставки датчика ветви ──────────────────────────────────────

/** Тело ветви, куда ставится датчик (then у if, тело цикла, try-блок). */
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

/** Тело else-ветки (plain else, НЕ else-if — там getElse() — IfStmt). */
Stmt elseBody(Stmt s) {
  result = s.(IfStmt).getElse() and
  not result instanceof IfStmt
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
 * Истинный конец оператора body (для закрывающей '}' обёртки одиночного
 * оператора, has_block=0). Для большинства Stmt — body.getLocation().
 * Для TryStmt без собственных {} вокруг (`while(...) try {...} catch(...){}`)
 * CodeQL даёт TryStmt.getLocation() только до конца try-блока, без catch —
 * нужен конец последнего catch-блока.
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

/**
 * constexpr-функция: __TRACE() вызывает обычную (не constexpr)
 * __trace_branch() — вставка в constexpr-вычисляемую функцию даёт каскад
 * ошибок компиляции. Ветвь остаётся в Перечень_ветвей, просто без геометрии.
 */
predicate noSensor(Stmt s) { s.getEnclosingFunction().isConstexpr() }

int insLine(Stmt s) {
  not noSensor(s) and exists(branchBody(s)) and result = branchBody(s).getLocation().getStartLine()
  or
  not noSensor(s) and s instanceof SwitchCase and result = s.(SwitchCase).getLocation().getEndLine()
  or
  (noSensor(s) or (not exists(branchBody(s)) and not s instanceof SwitchCase)) and result = 0
}

int insCol(Stmt s) {
  not noSensor(s) and exists(branchBody(s)) and result = branchBody(s).getLocation().getStartColumn()
  or
  // 1-based позиция символа ПОСЛЕ ':' метки case/default.
  not noSensor(s) and s instanceof SwitchCase and result = s.(SwitchCase).getLocation().getEndColumn() + 1
  or
  (noSensor(s) or (not exists(branchBody(s)) and not s instanceof SwitchCase)) and result = 0
}

/** has_block: 1 — тело в `{...}`, 0 — одиночный оператор, 2 — case/default. */
int hasBlockGeom(Stmt s) {
  not noSensor(s) and branchBody(s) instanceof BlockStmt and result = 1
  or
  not noSensor(s) and exists(branchBody(s)) and not branchBody(s) instanceof BlockStmt and result = 0
  or
  not noSensor(s) and s instanceof SwitchCase and result = 2
  or
  (noSensor(s) or (not exists(branchBody(s)) and not s instanceof SwitchCase)) and result = 0
}

int endLine(Stmt s) {
  not noSensor(s) and exists(branchBody(s)) and exists(int l | properStmtEnd(branchBody(s), l, _) | result = l)
  or
  not noSensor(s) and s instanceof SwitchCase and result = s.(SwitchCase).getLocation().getEndLine()
  or
  (noSensor(s) or (not exists(branchBody(s)) and not s instanceof SwitchCase)) and result = 0
}

int endCol(Stmt s) {
  not noSensor(s) and exists(branchBody(s)) and exists(int c | properStmtEnd(branchBody(s), _, c) | result = c)
  or
  not noSensor(s) and s instanceof SwitchCase and result = s.(SwitchCase).getLocation().getEndColumn()
  or
  (noSensor(s) or (not exists(branchBody(s)) and not s instanceof SwitchCase)) and result = 0
}

int elseInsLine(Stmt s) {
  not noSensor(s) and exists(elseBody(s)) and result = elseBody(s).getLocation().getStartLine()
  or
  (noSensor(s) or not exists(elseBody(s))) and result = 0
}

int elseInsCol(Stmt s) {
  not noSensor(s) and exists(elseBody(s)) and result = elseBody(s).getLocation().getStartColumn()
  or
  (noSensor(s) or not exists(elseBody(s))) and result = 0
}

int elseEndLine(Stmt s) {
  not noSensor(s) and exists(elseBody(s)) and exists(int l | properStmtEnd(elseBody(s), l, _) | result = l)
  or
  (noSensor(s) or not exists(elseBody(s))) and result = 0
}

int elseEndCol(Stmt s) {
  not noSensor(s) and exists(elseBody(s)) and exists(int c | properStmtEnd(elseBody(s), _, c) | result = c)
  or
  (noSensor(s) or not exists(elseBody(s))) and result = 0
}

/** Уникальный ID оператора (файл:строка) */
string getStmtId(Stmt s) {
  result = s.getFile().getBaseName() + ":" + s.getLocation().getStartLine().toString()
}

/** Возвращает "1" если оператор s находится в catch-блоке, иначе "0" */
string getInCatchMarker(Stmt s) {
  (exists(TryStmt ts, Handler h |
    h.getTryStmt() = ts and
    h.getBlock().getAChild+() = s
  ) and result = "1")
  or
  (not exists(TryStmt ts, Handler h |
    h.getTryStmt() = ts and
    h.getBlock().getAChild+() = s
  ) and result = "0")
}

from Function f, Stmt s
where
  f.hasDefinition() and
  isProjectFile(f.getFile()) and
  s.getEnclosingFunction() = f and
  (
    s instanceof IfStmt or
    s instanceof WhileStmt or
    s instanceof ForStmt or
    s instanceof DoStmt or
    s instanceof ReturnStmt or
    s instanceof TryStmt or
    s instanceof SwitchStmt or
    s instanceof SwitchCase or
    s instanceof BreakStmt or
    s instanceof ContinueStmt or
    s instanceof GotoStmt or
    s instanceof LabelStmt or
    s instanceof ExprStmt
  ) and
  // Исключаем управляющие конструкции, порождённые макросами (нет в исходниках)
  not isMacroGeneratedControl(s) and
  // То же для case/default, чей родительский switch порождён макросом.
  not (s instanceof SwitchCase and
       exists(SwitchStmt sw | s.(SwitchCase).getSwitchStmt() = sw | sw.getExpr().isInMacroExpansion())) and
  // И для самой метки, даже если switch и его выражение — нет: один
  // макровызов вида `case REP8(0xB8):` может разворачиваться в несколько
  // case-меток, физически указывающих на одно и то же место вызова.
  not (s instanceof SwitchCase and
       (s.isInMacroExpansion() or
        (exists(s.(SwitchCase).getExpr()) and s.(SwitchCase).getExpr().isInMacroExpansion())))
  // ПРИМ.: else-if (IfStmt в позиции else) НЕ исключается — это
  // самостоятельное ветвление, его нужно нумеровать как отдельный if (иначе
  // в Перечень_ветвей теряются все звенья цепочки кроме первого, а
  // инструментатор пропускает их датчики). Дублирования с "else" нет:
  // getElseLine/hasPlainElse не считают else-if плоской else-веткой.
select
  f.getQualifiedName() as func_name,
  f.getFile().getAbsolutePath() as func_file,
  getStmtId(s) as stmt_id,
  s.getLocation().getStartLine() as line_start,
  s.getLocation().getEndLine() as line_end,
  getStmtType(s) as stmt_type,
  getStmtLabel(s) as stmt_label,
  getElseLine(s) as else_line,
  getElseLineEnd(s) as else_line_end,
  getElseHasBlock(s) as else_has_block,
  getInCatchMarker(s) as in_catch,
  insLine(s) as ins_line, insCol(s) as ins_col, hasBlockGeom(s) as has_block,
  elseInsLine(s) as else_ins_line, elseInsCol(s) as else_ins_col,
  endLine(s) as end_line, endCol(s) as end_col,
  elseEndLine(s) as else_end_line, elseEndCol(s) as else_end_col
order by func_name, line_start
