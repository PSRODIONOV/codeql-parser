/**
 * Точки вставки датчиков динамического анализа (Python).
 *
 * entry  — позиция строки `def` (вставка декоратора @__trace.fn над ней).
 * branch — позиция первого оператора тела ветви (вставка _t перед ним с тем же отступом).
 *
 * Колонки: kind; func; file; ref_line; ins_line; ins_col; has_block; btype
 *   ref_line — строка def (entry) или строка оператора ветви (branch); ключ для #N.
 *   ins_line/ins_col — куда вставлять (1-based колонка = отступ).
 */
import python

predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}") and
  file.getExtension() = "py" and
  not file.getAbsolutePath().matches("%site-packages%") and
  not file.getAbsolutePath().matches("%__pycache__%") and
  not file.getAbsolutePath().matches("%.venv%") and
  not file.getAbsolutePath().matches("%/venv/%") and
  not file.getAbsolutePath().matches("%\\venv\\%")
}

predicate isBranch(Stmt s) {
  s instanceof If or s instanceof For or s instanceof While or s instanceof Try
}

/**
 * Настоящая def-функция/метод (не lambda и не comprehension). CodeQL Python
 * считает Function также списковые/словарные/множественные включения и генераторы
 * (имена listcomp/setcomp/dictcomp/genexpr) и lambda — их нельзя декорировать
 * как def и инструментировать декоратором, поэтому исключаем.
 */
predicate isRealDef(Function f) {
  not f.getName() = ["lambda", "listcomp", "setcomp", "dictcomp", "genexpr"]
}

string branchType(Stmt s) {
  s instanceof If and result = "if"
  or
  s instanceof For and result = "for"
  or
  s instanceof While and result = "while"
  or
  s instanceof Try and result = "try"
}

Stmt branchFirst(Stmt s) {
  result = s.(If).getBody().getItem(0)
  or
  result = s.(For).getBody().getItem(0)
  or
  result = s.(While).getBody().getItem(0)
  or
  result = s.(Try).getBody().getItem(0)
}

predicate probe(
  string kind, string func, string file, int refLine, int insLine, int insCol, string btype
) {
  exists(Function f |
    isProjectFile(f.getLocation().getFile()) and isRealDef(f)
  |
    kind = "entry" and
    func = f.getQualifiedName() and
    file = f.getLocation().getFile().getAbsolutePath() and
    refLine = f.getLocation().getStartLine() and
    insLine = f.getLocation().getStartLine() and
    insCol = f.getLocation().getStartColumn() and
    btype = "-"
  )
  or
  exists(Stmt s, Stmt b |
    isProjectFile(s.getLocation().getFile()) and
    isBranch(s) and
    s.getScope() instanceof Function and
    isRealDef(s.getScope()) and
    b = branchFirst(s)
  |
    kind = "branch" and
    func = s.getScope().(Function).getQualifiedName() and
    file = s.getLocation().getFile().getAbsolutePath() and
    refLine = s.getLocation().getStartLine() and
    insLine = b.getLocation().getStartLine() and
    insCol = b.getLocation().getStartColumn() and
    btype = branchType(s)
  )
}

from string kind, string func, string file, int refLine, int insLine, int insCol, string btype
where probe(kind, func, file, refLine, insLine, insCol, btype)
select kind, func, file, refLine, insLine, insCol, 1 as has_block, btype
order by file, refLine
