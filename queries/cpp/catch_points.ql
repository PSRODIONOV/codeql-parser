/**
 * Геометрия вставки датчика catch (C++). Отдельный запрос, а не колонка в
 * function_flow.ql: try может иметь несколько catch-клауз, а одна строка
 * function_flow.ql — один Stmt (try). Один результат на Handler, привязан
 * к ref_line своего try (мирроринг queries/java/catch_points.ql).
 *
 * Каждый catch получает свой номер ветви (см.
 * viz/flowchart_generator.py::generate_all, node["catch_branch_nums"]) — не
 * общий с try, отдельная строка в Перечень_ветвей.csv (Тип=catch).
 *
 * end_line/end_col нужны для макро-фоллбэка в instrument_cpp.py
 * (inline_candidate-резолюция, поиск конца многострочного макровызова —
 * см. _find_macro_call_end_idx); Java эти колонки не использует.
 *
 * Исключения (operator/isCompilerGenerated/isInMacroExpansion/isConstexpr на
 * enclosing-функции) исключают строку целиком, не только геометрию.
 *
 * Колонки: func; file; ref_line (строка try); ins_line; ins_col (начало
 * блока catch, после `{`); end_line; end_col (конец блока catch).
 */
import cpp

predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}") and
  file.getExtension() = ["cpp", "c", "h", "hpp"] and
  not file.getAbsolutePath().matches("%CMakeFiles%") and
  not file.getAbsolutePath().matches("%/usr/include%") and
  not file.getAbsolutePath().matches("%/usr/lib%") and
  not file.getAbsolutePath().matches("%/lib/%")
}

from TryStmt t, Handler h
where
  h.getTryStmt() = t and
  h.getEnclosingFunction().hasDefinition() and
  isProjectFile(h.getFile()) and
  not h.getEnclosingFunction().getName().indexOf("operator") = 0 and
  not h.getEnclosingFunction().isCompilerGenerated() and
  not h.getEnclosingFunction().isInMacroExpansion() and
  not h.getEnclosingFunction().isConstexpr()
select
  h.getEnclosingFunction().getQualifiedName() as func,
  h.getFile().getAbsolutePath() as file,
  t.getLocation().getStartLine() as ref_line,
  h.getBlock().getLocation().getStartLine() as ins_line,
  h.getBlock().getLocation().getStartColumn() as ins_col,
  h.getBlock().getLocation().getEndLine() as end_line,
  h.getBlock().getLocation().getEndColumn() as end_col
order by file, ref_line
