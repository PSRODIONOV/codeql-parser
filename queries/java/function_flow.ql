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
 * (for-each) не отслеживается — паритет с C++ (range-based for тоже без
 * ветви). */
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

// Геометрия вставки датчика ветви. branchBlock — тело ветви (then/цикл/
// try); для case/default нет своего {} — позиция вычисляется отдельно
// (см. insLine/insCol). catch не входит сюда (несколько catch на один try
// невозможно выразить одной колонкой на строке try) — его геометрия
// отдельно в catch_points.ql.
BlockStmt branchBlock(Stmt s) {
  result = s.(IfStmt).getThen()
  or
  result = s.(ForStmt).getStmt()
  or
  result = s.(WhileStmt).getStmt()
  or
  result = s.(DoStmt).getStmt()
  or
  result = s.(TryStmt).getBlock()
}

// Plain else (НЕ else-if — там getElse() возвращает IfStmt, не BlockStmt).
BlockStmt elseBlock(Stmt s) { result = s.(IfStmt).getElse() }

int insLine(Stmt s) {
  exists(BlockStmt b | b = branchBlock(s) | result = b.getLocation().getStartLine())
  or
  exists(SwitchCase sc | sc = s | result = sc.getLocation().getEndLine())
  or
  not exists(branchBlock(s)) and not s instanceof SwitchCase and result = 0
}

int insCol(Stmt s) {
  exists(BlockStmt b | b = branchBlock(s) | result = b.getLocation().getStartColumn())
  or
  // 1-based позиция символа ПОСЛЕ ':' метки.
  exists(SwitchCase sc | sc = s | result = sc.getLocation().getEndColumn() + 1)
  or
  not exists(branchBlock(s)) and not s instanceof SwitchCase and result = 0
}

/** has_block: 1 — тело в `{...}`, 2 — case/default (без {}), 0 — нет геометрии. */
int hasBlockGeom(Stmt s) {
  exists(branchBlock(s)) and result = 1
  or
  s instanceof SwitchCase and result = 2
  or
  not exists(branchBlock(s)) and not s instanceof SwitchCase and result = 0
}

int elseInsLine(Stmt s) {
  exists(BlockStmt b | b = elseBlock(s) | result = b.getLocation().getStartLine())
  or
  not exists(elseBlock(s)) and result = 0
}

int elseInsCol(Stmt s) {
  exists(BlockStmt b | b = elseBlock(s) | result = b.getLocation().getStartColumn())
  or
  not exists(elseBlock(s)) and result = 0
}

// end_line/end_col/else_end_line/else_end_col — для паритета схемы с cpp
// (RAW_SCHEMA["q_flow"] общая для языков). Java-тело всегда в `{}`, поэтому
// это настоящий конец блока, но instrument_java.py их не использует.
int endLine(Stmt s) {
  exists(BlockStmt b | b = branchBlock(s) | result = b.getLocation().getEndLine())
  or
  not exists(branchBlock(s)) and result = 0
}

int endCol(Stmt s) {
  exists(BlockStmt b | b = branchBlock(s) | result = b.getLocation().getEndColumn())
  or
  not exists(branchBlock(s)) and result = 0
}

int elseEndLine(Stmt s) {
  exists(BlockStmt b | b = elseBlock(s) | result = b.getLocation().getEndLine())
  or
  not exists(elseBlock(s)) and result = 0
}

int elseEndCol(Stmt s) {
  exists(BlockStmt b | b = elseBlock(s) | result = b.getLocation().getEndColumn())
  or
  not exists(elseBlock(s)) and result = 0
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
  getInCatchMarker(s) as in_catch,
  insLine(s) as ins_line,
  insCol(s) as ins_col,
  hasBlockGeom(s) as has_block,
  elseInsLine(s) as else_ins_line,
  elseInsCol(s) as else_ins_col,
  endLine(s) as end_line,
  endCol(s) as end_col,
  elseEndLine(s) as else_end_line,
  elseEndCol(s) as else_end_col
