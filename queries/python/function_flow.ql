import python

/** Файл принадлежит тестовому проекту Python */
predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}") and
  file.getExtension() = "py" and
  not file.getAbsolutePath().matches("%site-packages%") and
  not file.getAbsolutePath().matches("%__pycache__%") and
  not file.getAbsolutePath().matches("%.venv%") and
  not file.getAbsolutePath().matches("%/venv/%") and
  not file.getAbsolutePath().matches("%\\venv\\%")
}

/** Уникальный ID оператора: файл:строка */
string getStmtId(Stmt s) {
  result = s.getLocation().getFile().getBaseName() + ":" + s.getLocation().getStartLine().toString()
}

/**
 * Реальная последняя строка оператора (включая тело).
 * В Python CodeQL у составных операторов (if/while/for/try) getEndLine() возвращает
 * только строку ЗАГОЛОВКА, из-за чего иерархия по диапазонам строк рассыпалась
 * (тело не вкладывалось). Берём максимум по всем вложенным AST-узлам.
 */
int getEndLine(Stmt s) {
  result = max(AstNode n | n = s.getAChildNode*() | n.getLocation().getEndLine())
}

/** Тип оператора */
string getStmtType(Stmt s) {
  s instanceof If and result = "if"
  or
  s instanceof For and result = "for"
  or
  s instanceof While and result = "while"
  or
  s instanceof Try and result = "try"
  or
  s instanceof Return and result = "return"
  or
  s instanceof Raise and result = "throw"
  or
  s instanceof With and result = "with"
  or
  s instanceof ExprStmt and result = "expr"
  or
  s instanceof Break and result = "break"
  or
  s instanceof Continue and result = "continue"
  or
  (s instanceof Assign or s instanceof AugAssign) and result = "other"
}

/** Метка оператора для блок-схемы */
string getStmtLabel(Stmt s) {
  s instanceof If and result = "if (" + s.(If).getTest().toString() + ")"
  or
  s instanceof For and result = "for " + s.(For).getTarget().toString() + " in ..."
  or
  s instanceof While and result = "while (" + s.(While).getTest().toString() + ")"
  or
  s instanceof Try and result = "try"
  or
  s instanceof Return and
  (
    if exists(s.(Return).getValue())
    then result = "return " + s.(Return).getValue().toString()
    else result = "return"
  )
  or
  s instanceof Raise and
  (
    if exists(s.(Raise).getRaisedException())
    then result = "raise " + s.(Raise).getRaisedException().toString()
    else result = "raise"
  )
  or
  s instanceof With and result = "with ..."
  or
  s instanceof ExprStmt and result = s.(ExprStmt).getValue().toString()
  or
  s instanceof Break and result = "break"
  or
  s instanceof Continue and result = "continue"
  or
  s instanceof Assign and result = s.toString()
  or
  s instanceof AugAssign and result = s.toString()
}

/**
 * Строка начала ветки else/except.
 * If.getOrelse(int n) индексирует операторы else-блока по позиции.
 * Try.getAHandler() возвращает обработчики исключений (ExceptStmt).
 */
string getElseLine(Stmt s) {
  s instanceof If and
  exists(s.(If).getOrelse(0)) and
  result = s.(If).getOrelse(0).getLocation().getStartLine().toString()
  or
  s instanceof Try and
  exists(s.(Try).getAHandler()) and
  result = min(ExceptStmt h | h = s.(Try).getAHandler() |
    h.getLocation().getStartLine()).toString()
  or
  not (s instanceof If and exists(s.(If).getOrelse(0))) and
  not (s instanceof Try and exists(s.(Try).getAHandler())) and
  result = ""
}

/**
 * Оператор находится внутри except-блока: "1" или "0".
 * Определяем по вхождению строк оператора в диапазон строк ExceptStmt
 * (getParent+() несовместим с StmtList → ExceptStmt в Python CodeQL 7.x).
 */
string getInCatchMarker(Stmt s) {
  exists(ExceptStmt h |
    h.getScope() = s.getScope() and
    s.getLocation().getStartLine() >= h.getLocation().getStartLine() and
    s.getLocation().getEndLine() <= h.getLocation().getEndLine()
  ) and result = "1"
  or
  not exists(ExceptStmt h |
    h.getScope() = s.getScope() and
    s.getLocation().getStartLine() >= h.getLocation().getStartLine() and
    s.getLocation().getEndLine() <= h.getLocation().getEndLine()
  ) and result = "0"
}

from Function f, Stmt s
where
  f.getName() != "" and
  s.getScope() = f and
  isProjectFile(f.getLocation().getFile()) and
  exists(getStmtType(s)) and
  exists(getStmtLabel(s))
select
  f.getQualifiedName() as func_name,
  f.getLocation().getFile().getAbsolutePath() as func_file,
  getStmtId(s) as stmt_id,
  s.getLocation().getStartLine() as line_start,
  getEndLine(s) as line_end,
  getStmtType(s) as stmt_type,
  getStmtLabel(s) as stmt_label,
  getElseLine(s) as else_line,
  getInCatchMarker(s) as in_catch
order by func_name, line_start
