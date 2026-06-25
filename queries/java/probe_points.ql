/**
 * Точки вставки датчиков динамического анализа (Java).
 *
 * entry  — тело ФО оборачивается: после `{` (или после super()/this() в
 *          конструкторе) вставляется `hit(fo,0); try {`, перед `}` тела —
 *          `} finally { hit(fo,-1); }`.
 * branch — после `{` блока ветви (then/тело/try) вставляется `hit(fo,br)`.
 *
 * Колонки: kind; func; file; ref_line; ins_line; ins_col; has_block; btype;
 * end_line; end_col — НАЗВАНИЯ СОВПАДАЮТ с queries/cpp/probe_points.ql (см.
 * RAW_SCHEMA["q_probe"] в core/project_db.py: одна таблица project.db делится
 * между языками по именам колонок). has_block здесь всегда "1" — у Java нет
 * безблочных (без {}) форм веток/тел в текущей геометрии (branchBlock/explicitCtorCall
 * выбирают только BlockStmt), в отличие от C/C++.
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
  string kind, string func, string file, int ref_line,
  int ins_line, int ins_col, int has_block, string btype, int end_line, int end_col
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
    ref_line = c.getLocation().getStartLine() and
    end_line = body.getLocation().getEndLine() and
    end_col = body.getLocation().getEndColumn() and
    has_block = 1 and
    btype = "-" and
    (
      // конструктор с super()/this() — вставка ПОСЛЕ него
      exists(Stmt first |
        explicitCtorCall(body, first) and
        ins_line = first.getLocation().getEndLine() and
        ins_col = first.getLocation().getEndColumn()
      )
      or
      not explicitCtorCall(body, _) and
      ins_line = body.getLocation().getStartLine() and
      ins_col = body.getLocation().getStartColumn()
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
    ref_line = s.getLocation().getStartLine() and
    ins_line = b.getLocation().getStartLine() and
    ins_col = b.getLocation().getStartColumn() and
    has_block = 1 and
    end_line = 0 and
    end_col = 0 and
    btype = branchType(s)
  )
}

from
  string kind, string func, string file, int ref_line,
  int ins_line, int ins_col, int has_block, string btype, int end_line, int end_col
where probe(kind, func, file, ref_line, ins_line, ins_col, has_block, btype, end_line, end_col)
select kind, func, file, ref_line, ins_line, ins_col, has_block, btype, end_line, end_col
order by file, ref_line
