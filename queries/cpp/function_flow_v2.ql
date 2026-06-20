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

// "else if" — это IfStmt в позиции else. Он НЕ является плоской else-веткой:
// это самостоятельное ветвление (своя строка в выводе, см. условие where).
// Поэтому для родительского if такой else НЕ считается else-веткой (иначе
// flowchart_generator синтезировал бы фантомную "else"-запись, дублирующую
// уже существующий if-узел else if). Плоский else (блок или одиночный
// оператор, но НЕ IfStmt) — считается как и раньше.
predicate hasPlainElse(IfStmt s) {
  exists(s.getElse()) and not s.getElse() instanceof IfStmt
}

/** Строка начала else/catch-ветки, иначе 0 */
int getElseLine(Stmt s) {
  hasPlainElse(s) and
  result = s.(IfStmt).getElse().getLocation().getStartLine()
  or
  s instanceof TryStmt and
  result = min(Handler h | h.getTryStmt() = s | h.getLocation().getStartLine())
  or
  not hasPlainElse(s) and
  not s instanceof TryStmt and
  result = 0
}

/** Строка конца else-ветки, иначе 0 */
int getElseLineEnd(Stmt s) {
  hasPlainElse(s) and
  result = s.(IfStmt).getElse().getLocation().getEndLine()
  or
  not hasPlainElse(s) and
  result = 0
}

/** else-ветва в { } (1) или одиночный оператор (0), иначе 0 */
int getElseHasBlock(Stmt s) {
  hasPlainElse(s) and
  s.(IfStmt).getElse() instanceof BlockStmt and
  result = 1
  or
  hasPlainElse(s) and
  not s.(IfStmt).getElse() instanceof BlockStmt and
  result = 0
  or
  not hasPlainElse(s) and
  result = 0
}

/** Позиция символа начала тела ({) — столбец (1-based), иначе 0 */
int getInsCol(Stmt s) {
  s instanceof IfStmt and result = s.(IfStmt).getThen().getLocation().getStartColumn()
  or
  s instanceof WhileStmt and result = s.(WhileStmt).getStmt().getLocation().getStartColumn()
  or
  s instanceof ForStmt and result = s.(ForStmt).getStmt().getLocation().getStartColumn()
  or
  s instanceof DoStmt and result = s.(DoStmt).getStmt().getLocation().getStartColumn()
  or
  s instanceof TryStmt and result = s.(TryStmt).getStmt().getLocation().getStartColumn()
  or
  not s instanceof IfStmt and not s instanceof WhileStmt and not s instanceof ForStmt
    and not s instanceof DoStmt and not s instanceof TryStmt and
  result = 0
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
       exists(SwitchStmt sw | s.(SwitchCase).getSwitchStmt() = sw | sw.getExpr().isInMacroExpansion()))
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
  getInsCol(s) as ins_col,
  getInCatchMarker(s) as in_catch
order by func_name, line_start
