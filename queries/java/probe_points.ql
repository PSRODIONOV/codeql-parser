/**
 * Точки вставки датчиков динамического анализа (Java).
 *
 * entry  — тело ФО оборачивается: после `{` (или после super()/this() в
 *          конструкторе) вставляется `hit(fo,0); try {`, перед `}` тела —
 *          `} finally { hit(fo,-1); }`.
 * branch — после `{` блока ветви (then/тело/try/catch/else) вставляется
 *          `hit(fo,br)`; для case/default (has_block=2) — сразу после ':'
 *          метки, без обёртки в {} (см. has_block=2 ниже, мирроринг
 *          queries/cpp/probe_points.ql).
 *
 * Колонки: kind; func; file; ref_line; ins_line; ins_col; has_block; btype;
 * end_line; end_col — НАЗВАНИЯ СОВПАДАЮТ с queries/cpp/probe_points.ql (см.
 * RAW_SCHEMA["q_probe"] в core/project_db.py: одна таблица project.db делится
 * между языками по именам колонок). has_block=1 везде, КРОМЕ case/default
 * (has_block=2) — у Java нет безблочных (без {}) форм if/for/while/do/try
 * в текущей геометрии (branchBlock/explicitCtorCall выбирают только
 * BlockStmt), в отличие от C/C++.
 */
import java

predicate isProjectFile(File file) { file.getAbsolutePath().matches("${PROJECT_PATTERN}") }

string qname(Callable c) {
  result = c.getDeclaringType().getQualifiedName() + "." + c.getName()
}

// EnhancedForStmt (for-each) НЕ отслеживается — паритет с C++, где range-based
// for (CXXForRangeStmt) тоже не даёт ветви: итерация "для каждого элемента"
// не содержит наблюдаемой точки решения (нет условия, которое могло бы
// принять разные значения true/false), в отличие от классического ForStmt
// с явным условием выхода. См. docs/PRINCIPLES_C_CPP.md.
string branchType(Stmt s) {
  s instanceof IfStmt and result = "if"
  or
  s instanceof ForStmt and result = "for"
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
  result = s.(WhileStmt).getStmt()
  or
  result = s.(DoStmt).getStmt()
  or
  result = s.(TryStmt).getBlock()
}

// Plain else (НЕ else-if — там getElse() возвращает IfStmt, не BlockStmt,
// и просто не унифицируется с результатом BlockStmt-типа). else-if
// продолжает обрабатываться как обычный IfStmt в основной branch-клаузе.
BlockStmt elseBlock(IfStmt s) { s.getElse() = result }

// "default" или "case" — аналог caseBtype в queries/cpp/probe_points.ql.
string caseBtype(SwitchCase sc) {
  sc instanceof DefaultCase and result = "default"
  or
  not sc instanceof DefaultCase and result = "case"
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
  or
  // Plain else (else-if обрабатывается выше как обычный IfStmt).
  exists(IfStmt ifs, BlockStmt b |
    isProjectFile(ifs.getCompilationUnit().getFile()) and
    b = elseBlock(ifs) and
    not exists(FunctionalExpr fe | fe.asMethod() = ifs.getEnclosingCallable())
  |
    kind = "branch" and
    func = qname(ifs.getEnclosingCallable()) and
    file = ifs.getCompilationUnit().getFile().getAbsolutePath() and
    ref_line = ifs.getLocation().getStartLine() and
    ins_line = b.getLocation().getStartLine() and
    ins_col = b.getLocation().getStartColumn() and
    has_block = 1 and
    end_line = 0 and
    end_col = 0 and
    btype = "else"
  )
  or
  // switch case/default — метки делят ОДИН общий блок тела switch (нет
  // своих {}), датчик вставляется ПРЯМО после ':' метки (has_block=2),
  // см. подробный комментарий о том же в queries/cpp/probe_points.ql.
  exists(SwitchStmt sw, SwitchCase sc |
    sc = sw.getACase() and
    isProjectFile(sc.getCompilationUnit().getFile()) and
    not exists(FunctionalExpr fe | fe.asMethod() = sw.getEnclosingCallable())
  |
    kind = "branch" and
    func = qname(sw.getEnclosingCallable()) and
    file = sc.getCompilationUnit().getFile().getAbsolutePath() and
    // refLine — строка самой метки (как у cpp): по ней инструментатор ищет
    // номер ветви в Перечень_ветвей, где каждая метка — отдельная строка.
    ref_line = sc.getLocation().getStartLine() and
    ins_line = sc.getLocation().getEndLine() and
    ins_col = sc.getLocation().getEndColumn() + 1 and
    has_block = 2 and
    btype = caseBtype(sc) and
    end_line = sc.getLocation().getEndLine() and
    end_col = sc.getLocation().getEndColumn()
  )
  or
  // catch — тело уже целиком в {} (как у try), тот же has_block=1.
  // ref_line — строка САМОГО try (как у cpp): catch делит номер ветви с
  // try-точкой того же TryStmt (Перечень_ветвей не содержит отдельной
  // строки для catch — это датчик ПОКРЫТИЯ, не отдельная "ветвь", см.
  // docs/PRINCIPLES_C_CPP.md), поэтому _lookup_br находит ту же запись.
  exists(TryStmt t, CatchClause cc |
    cc = t.getACatchClause() and
    isProjectFile(cc.getCompilationUnit().getFile()) and
    not exists(FunctionalExpr fe | fe.asMethod() = cc.getBlock().getEnclosingCallable())
  |
    kind = "branch" and
    func = qname(cc.getBlock().getEnclosingCallable()) and
    file = cc.getCompilationUnit().getFile().getAbsolutePath() and
    ref_line = t.getLocation().getStartLine() and
    ins_line = cc.getBlock().getLocation().getStartLine() and
    ins_col = cc.getBlock().getLocation().getStartColumn() and
    has_block = 1 and
    end_line = 0 and
    end_col = 0 and
    btype = "catch"
  )
}

from
  string kind, string func, string file, int ref_line,
  int ins_line, int ins_col, int has_block, string btype, int end_line, int end_col
where probe(kind, func, file, ref_line, ins_line, ins_col, has_block, btype, end_line, end_col)
select kind, func, file, ref_line, ins_line, ins_col, has_block, btype, end_line, end_col
order by file, ref_line
