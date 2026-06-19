/**
 * Точки вставки датчиков динамического анализа (JavaScript).
 *
 * entry  — тело ФО оборачивается: после `{` тела вставляется `hit(fo,0); try {`,
 *          перед `}` тела — `} finally { hit(fo,-1); }`. Нужны обе позиции скобок.
 * branch — после `{` блока ветви (then/тело/try) вставляется `hit(fo,br)`.
 *
 * Колонки: kind; func; file; ref_line; open_line; open_col; close_line; close_col; btype
 *   open_col/close_col — 1-based колонки `{` и `}`; вставка сразу ПОСЛЕ `{` и ПЕРЕД `}`.
 */
import javascript

predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}") and
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

string branchType(Stmt s) {
  s instanceof IfStmt and result = "if"
  or
  (s instanceof ForStmt or s instanceof ForInStmt or s instanceof ForOfStmt) and result = "for"
  or
  (s instanceof WhileStmt or s instanceof DoWhileStmt) and result = "while"
  or
  s instanceof TryStmt and result = "try"
}

BlockStmt branchBlock(Stmt s) {
  result = s.(IfStmt).getThen()
  or
  result = s.(ForStmt).getBody()
  or
  result = s.(ForInStmt).getBody()
  or
  result = s.(ForOfStmt).getBody()
  or
  result = s.(WhileStmt).getBody()
  or
  result = s.(DoWhileStmt).getBody()
  or
  result = s.(TryStmt).getBody()
}

predicate probe(
  string kind, string func, string file, int refLine,
  int openLine, int openCol, int closeLine, int closeCol, string btype
) {
  // Вход/выход ФО — тело-блок функции
  exists(Function f, BlockStmt body |
    isProjectFile(f.getFile()) and body = f.getBody() and exists(qname(f))
  |
    kind = "entry" and
    func = qname(f) and
    file = f.getFile().getAbsolutePath() and
    refLine = f.getLocation().getStartLine() and
    openLine = body.getLocation().getStartLine() and
    openCol = body.getLocation().getStartColumn() and
    closeLine = body.getLocation().getEndLine() and
    closeCol = body.getLocation().getEndColumn() and
    btype = "-"
  )
  or
  // Ветвь — блок then/тело/try
  exists(Stmt s, BlockStmt b |
    isProjectFile(s.getFile()) and
    s.getContainer() instanceof Function and
    exists(branchType(s)) and
    b = branchBlock(s)
  |
    kind = "branch" and
    func = qname(s.getContainer()) and
    file = s.getFile().getAbsolutePath() and
    refLine = s.getLocation().getStartLine() and
    openLine = b.getLocation().getStartLine() and
    openCol = b.getLocation().getStartColumn() and
    closeLine = 0 and
    closeCol = 0 and
    btype = branchType(s)
  )
}

from
  string kind, string func, string file, int refLine,
  int openLine, int openCol, int closeLine, int closeCol, string btype
where probe(kind, func, file, refLine, openLine, openCol, closeLine, closeCol, btype)
select kind, func, file, refLine, openLine, openCol, closeLine, closeCol, btype
order by file, refLine
