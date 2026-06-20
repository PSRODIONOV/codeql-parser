import javascript

predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}") and
  not file.getAbsolutePath().matches("%test-project-js-db%") and
  not file.getAbsolutePath().matches("%node_modules%")
}

string qname(Function f) {
  exists(MethodDefinition md | md.getBody() = f and md.getName() != "constructor" |
    result = md.getDeclaringClass().getName() + "." + md.getName()
  )
  or
  exists(MethodDefinition md | md.getBody() = f and md.getName() = "constructor" |
    result = md.getDeclaringClass().getName() + ".constructor"
  )
  or
  not exists(MethodDefinition md | md.getBody() = f) and
  f.getName() != "" and
  result = f.getName()
}

string getStmtId(Stmt s) {
  result = s.getFile().getBaseName() + ":" + s.getLocation().getStartLine().toString()
}

string getStmtType(Stmt s) {
  s instanceof IfStmt and result = "if"
  or
  (s instanceof ForStmt or s instanceof ForInStmt or s instanceof ForOfStmt) and result = "for"
  or
  (s instanceof WhileStmt or s instanceof DoWhileStmt) and result = "while"
  or
  s instanceof ReturnStmt and result = "return"
  or
  s instanceof ThrowStmt and result = "throw"
  or
  s instanceof TryStmt and result = "try"
  or
  s instanceof BreakStmt and result = "break"
  or
  s instanceof ContinueStmt and result = "continue"
  or
  (s instanceof ExprStmt or s instanceof DeclStmt) and result = "other"
}

string getElseLine(Stmt s) {
  exists(IfStmt ifs | ifs = s and exists(ifs.getElse()) |
    result = ifs.getElse().getLocation().getStartLine().toString()
  )
  or
  exists(TryStmt ts | ts = s and exists(ts.getCatchClause()) |
    result = ts.getCatchClause().getLocation().getStartLine().toString()
  )
  or
  not (s instanceof IfStmt and exists(s.(IfStmt).getElse())) and
  not (s instanceof TryStmt and exists(s.(TryStmt).getCatchClause())) and
  result = ""
}

/** Определяет, находится ли оператор s внутри catch-блока */
string getInCatchMarker(Stmt s) {
  (exists(TryStmt ts |
    ts.getCatchClause().getAChild*() = s
  ) and result = "1")
  or
  (not exists(TryStmt ts |
    ts.getCatchClause().getAChild*() = s
  ) and result = "0")
}

from Stmt s, Function f
where
  isProjectFile(f.getFile()) and
  s.getContainer() = f and
  s.getLocation().getStartLine() > 0 and
  exists(getStmtType(s)) and
  exists(qname(f))
select
  qname(f) as func_name,
  f.getFile().getAbsolutePath() as func_file,
  getStmtId(s) as stmt_id,
  s.getLocation().getStartLine() as line,
  s.getLocation().getEndLine() as line_end,
  getStmtType(s) as stmt_type,
  getStmtType(s) as stmt_label,
  getElseLine(s) as else_line,
  getInCatchMarker(s) as in_catch
