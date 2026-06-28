/**
 * Геометрия вставки датчика catch (Java). Отдельный запрос, а не колонка в
 * function_flow.ql: try может иметь несколько catch-клауз, а одна строка
 * function_flow.ql — один Stmt (try). Один результат на CatchClause, привязан
 * к ref_line своего try.
 *
 * Каждая catch-клауза получает свой номер ветви (см.
 * viz/flowchart_generator.py::generate_all, node["catch_branch_nums"]) —
 * не общий с try, отдельная строка в Перечень_ветвей.csv (Тип=catch).
 *
 * Колонки: func; file; ref_line (строка try); ins_line; ins_col (начало
 * блока catch, после `{`); end_line; end_col (конец блока catch — для
 * паритета схемы с queries/cpp/catch_points.ql; instrument_java.py их
 * не использует).
 */
import java

predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}")
}

string qname(Callable c) {
  result = c.getDeclaringType().getQualifiedName() + "." + c.getName()
}

from TryStmt t, CatchClause cc
where
  cc = t.getACatchClause() and
  isProjectFile(cc.getCompilationUnit().getFile())
select
  qname(cc.getBlock().getEnclosingCallable()) as func,
  cc.getCompilationUnit().getFile().getAbsolutePath() as file,
  t.getLocation().getStartLine() as ref_line,
  cc.getBlock().getLocation().getStartLine() as ins_line,
  cc.getBlock().getLocation().getStartColumn() as ins_col,
  cc.getBlock().getLocation().getEndLine() as end_line,
  cc.getBlock().getLocation().getEndColumn() as end_col
order by file, ref_line
