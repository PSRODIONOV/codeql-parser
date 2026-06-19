/**
 * Точки вставки датчиков динамического анализа (Java).
 *
 * entry  — тело ФО оборачивается: после `{` (или после super()/this() в
 *          конструкторе) вставляется `hit(fo,0); try {`, перед `}` тела —
 *          `} finally { hit(fo,-1); }`.
 * branch — после `{` блока ветви (then/тело/try) вставляется `hit(fo,br)`.
 *
 * Колонки: kind; func; file; ref_line; open_line; open_col; close_line; close_col; btype
 */
import java

predicate isProjectFile(File file) { file.getAbsolutePath().matches("${PROJECT_PATTERN}") }

string qname(Callable c) {
  result = c.getDeclaringType().getQualifiedName() + "." + c.getName()
}

string branchType(Stmt s) {
  s instanceof IfStmt and result = "if"
  or
  (s instanceof ForStmt or s instanceof EnhancedForStmt) and result = "for"
  or
  s instanceof WhileStmt and result = "while"
  or
  s instanceof DoStmt and result = "do"
  or
  s instanceof TryStmt and result = "try"
}

BlockStmt branchBlock(Stmt s) {
  result = s.(IfStmt).getThen()
  or
  result = s.(ForStmt).getStmt()
  or
  result = s.(EnhancedForStmt).getStmt()
  or
  result = s.(WhileStmt).getStmt()
  or
  result = s.(DoStmt).getStmt()
  or
  result = s.(TryStmt).getBlock()
}

predicate explicitCtorCall(BlockStmt b, Stmt first) {
  first = b.getStmt(0) and
  (first instanceof SuperConstructorInvocationStmt or first instanceof ThisConstructorInvocationStmt) and
  // ТОЛЬКО явный вызов в исходнике: его позиция строго ПОСЛЕ открывающей `{`
  // тела. Неявный (сгенерированный) super() имеет вырожденную локацию на
  // строке сигнатуры конструктора — его учитывать нельзя.
  (
    first.getLocation().getStartLine() > b.getLocation().getStartLine()
    or
    first.getLocation().getStartLine() = b.getLocation().getStartLine() and
    first.getLocation().getStartColumn() > b.getLocation().getStartColumn()
  )
}

predicate probe(
  string kind, string func, string file, int refLine,
  int openLine, int openCol, int closeLine, int closeCol, string btype
) {
  // Вход/выход ФО
  exists(Callable c, BlockStmt body |
    isProjectFile(c.getCompilationUnit().getFile()) and body = c.getBody() and exists(qname(c)) and
    // Исключаем сгенерированные дефолтные конструкторы (нет тела в исходнике).
    not c.(Constructor).isDefaultConstructor() and
    // Исключаем синтетические методы лямбд и method reference (их «тело» —
    // выражение, обёртка ломает синтаксис; нельзя инструментировать как метод).
    not exists(FunctionalExpr fe | fe.asMethod() = c)
  |
    kind = "entry" and
    func = qname(c) and
    file = c.getCompilationUnit().getFile().getAbsolutePath() and
    refLine = c.getLocation().getStartLine() and
    closeLine = body.getLocation().getEndLine() and
    closeCol = body.getLocation().getEndColumn() and
    btype = "-" and
    (
      // конструктор с super()/this() — вставка ПОСЛЕ него
      exists(Stmt first |
        explicitCtorCall(body, first) and
        openLine = first.getLocation().getEndLine() and
        openCol = first.getLocation().getEndColumn()
      )
      or
      not explicitCtorCall(body, _) and
      openLine = body.getLocation().getStartLine() and
      openCol = body.getLocation().getStartColumn()
    )
  )
  or
  // Ветвь
  exists(Stmt s, BlockStmt b |
    isProjectFile(s.getCompilationUnit().getFile()) and
    exists(branchType(s)) and
    b = branchBlock(s) and
    not exists(FunctionalExpr fe | fe.asMethod() = s.getEnclosingCallable())
  |
    kind = "branch" and
    func = qname(s.getEnclosingCallable()) and
    file = s.getCompilationUnit().getFile().getAbsolutePath() and
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
