import java

predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}")
}

string qname(Callable c) {
  result = c.getDeclaringType().getQualifiedName() + "." + c.getName()
}

/** Уникальный идентификатор оператора: файл:строка */
string getStmtId(Stmt s) {
  result = s.getFile().getBaseName() + ":" + s.getLocation().getStartLine().toString()
}

/**
 * Полная конечная строка оператора — максимум по самому оператору и всем его
 * вложенным узлам. В Java getLocation() у if/for/while покрывает только
 * заголовок, из-за чего тело не вкладывается в иерархию блок-схемы. Берём
 * максимум по getAChild*(), чтобы диапазон охватывал весь блок.
 */
int getFullEndLine(Stmt s) {
  result = max(Element e | e = s.getAChild*() | e.getLocation().getEndLine())
}

/** "case X" или "default" — для метки/типа case-точки switch (как в C++). */
predicate isDefaultCase(SwitchCase sc) { sc instanceof DefaultCase }

/** Классификация оператора по типу для блок-схемы. EnhancedForStmt
 * (for-each) НЕ отслеживается — паритет с C++ (range-based for тоже без
 * ветви, см. probe_points.ql). */
string getStmtType(Stmt s) {
  s instanceof IfStmt and result = "if"
  or
  s instanceof ForStmt and result = "for"
  or
  s instanceof WhileStmt and result = "while"
  or
  s instanceof DoStmt and result = "do"
  or
  s instanceof ReturnStmt and result = "return"
  or
  s instanceof ThrowStmt and result = "throw"
  or
  s instanceof TryStmt and result = "try"
  or
  s instanceof SwitchStmt and result = "switch"
  or
  // case/default — НЕ собственный узел блок-схемы (как и else), а метка
  // границы ветви switch; см. _build_hierarchy/_render_node в
  // viz/flowchart_generator.py — case-строки используются только для
  // партиционирования и текста на ребре (мирроринг queries/cpp/function_flow.ql).
  s instanceof SwitchCase and isDefaultCase(s) and result = "default"
  or
  s instanceof SwitchCase and not isDefaultCase(s) and result = "case"
  or
  s instanceof BreakStmt and result = "break"
  or
  s instanceof ContinueStmt and result = "continue"
  or
  (s instanceof ExprStmt or s instanceof LocalVariableDeclStmt) and result = "other"
}

string getStmtLabel(Stmt s) { result = getStmtType(s) }

/** Строка начала else/catch-ветки, иначе пусто. */
string getElseLine(Stmt s) {
  exists(IfStmt ifs | ifs = s and exists(ifs.getElse()) |
    result = ifs.getElse().getLocation().getStartLine().toString()
  )
  or
  exists(TryStmt ts | ts = s and exists(ts.getACatchClause()) |
    result = min(CatchClause cc | cc = ts.getACatchClause() | cc.getLocation().getStartLine()).toString()
  )
  or
  not (s instanceof IfStmt and exists(s.(IfStmt).getElse())) and
  not (s instanceof TryStmt and exists(s.(TryStmt).getACatchClause())) and
  result = ""
}

/** Определяет, находится ли оператор s внутри catch-блока */
string getInCatchMarker(Stmt s) {
  (exists(TryStmt ts, CatchClause cc |
    cc = ts.getACatchClause() and
    cc.getBlock().getAChild*() = s
  ) and result = "1")
  or
  (not exists(TryStmt ts, CatchClause cc |
    cc = ts.getACatchClause() and
    cc.getBlock().getAChild*() = s
  ) and result = "0")
}

from Stmt s, Callable f
where
  isProjectFile(f.getFile()) and
  s.getEnclosingCallable() = f and
  s.getLocation().getStartLine() > 0 and
  exists(getStmtType(s))
select
  qname(f) as func_name,
  f.getFile().getAbsolutePath() as func_file,
  getStmtId(s) as stmt_id,
  s.getLocation().getStartLine() as line_start,
  getFullEndLine(s) as line_end,
  getStmtType(s) as stmt_type,
  getStmtLabel(s) as stmt_label,
  getElseLine(s) as else_line,
  getInCatchMarker(s) as in_catch
