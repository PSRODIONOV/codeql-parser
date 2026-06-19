import cpp

/** Файл принадлежит тестовому проекту */
predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}") and
  file.getBaseName() = "main.cpp" or
  file.getBaseName() = "utils.cpp" or
  file.getBaseName() = "utils.h" or
  file.getBaseName() = "calculator.cpp" or
  file.getBaseName() = "calculator.h" or
  file.getBaseName() = "string_processor.cpp" or
  file.getBaseName() = "string_processor.h" or
  file.getBaseName() = "classes.cpp" or
  file.getBaseName() = "classes.h"
}

/** Тип оператора */
string getStmtType(Stmt s) {
  s instanceof DeclStmt and result = "decl"
  or
  s instanceof IfStmt and result = "if"
  or
  s instanceof WhileStmt and result = "while"
  or
  s instanceof ForStmt and result = "for"
  or
  s instanceof DoStmt and result = "do"
  or
  s instanceof ReturnStmt and result = "return"
  or
  s instanceof ExprStmt and result = "expr"
  or
  result = "other"
}

/** Читаемая метка оператора */
string getStmtLabel(Stmt s) {
  exists(IfStmt ifs | ifs = s |
    result = "if (" + ifs.getCondition().toString() + ")"
  )
  or
  exists(WhileStmt ws | ws = s |
    result = "while (" + ws.getCondition().toString() + ")"
  )
  or
  exists(ForStmt fs | fs = s |
    result = "for (" +
      fs.getInitialization().toString() + "; " +
      fs.getCondition().toString() + "; " +
      fs.getUpdate().toString() + ")"
  )
  or
  exists(DoStmt ds | ds = s |
    result = "do ... while (" + ds.getCondition().toString() + ")"
  )
  or
  exists(ReturnStmt rs | rs = s |
    exists(rs.getExpr()) and result = "return " + rs.getExpr().toString()
    or not exists(rs.getExpr()) and result = "return"
  )
  or
  result = s.toString()
}

/** Уникальный ID оператора (файл:строка) */
string getStmtId(Stmt s) {
  result = s.getFile().getBaseName() + ":" + s.getLocation().getStartLine().toString()
}

/** ID родительского оператора, если оператор вложен в if/while/for */
string getParentId(Stmt s) {
  // Прямой потомок if-then
  exists(IfStmt ifs | ifs.getThen() = s |
    result = getStmtId(ifs)
  )
  or
  // Прямой потомок if-else
  exists(IfStmt ifs | ifs.getElse() = s |
    result = getStmtId(ifs)
  )
  or
  // Прямой потомок while
  exists(WhileStmt ws | ws.getStmt() = s |
    result = getStmtId(ws)
  )
  or
  // Прямой потомок for
  exists(ForStmt fs | fs.getStmt() = s |
    result = getStmtId(fs)
  )
  or
  // Прямой потомок do-while
  exists(DoStmt ds | ds.getStmt() = s |
    result = getStmtId(ds)
  )
  or
  // Оператор внутри BlockStmt который является then ветвью
  exists(BlockStmt thenBlock, IfStmt ifs |
    thenBlock = ifs.getThen() and thenBlock.getAStmt() = s |
    result = getStmtId(ifs)
  )
  or
  // Оператор внутри BlockStmt который является else ветвью
  exists(BlockStmt elseBlock, IfStmt ifs |
    elseBlock = ifs.getElse() and elseBlock.getAStmt() = s |
    result = getStmtId(ifs)
  )
  or
  // Оператор внутри BlockStmt который является телом while
  exists(BlockStmt whileBlock, WhileStmt ws |
    whileBlock = ws.getStmt() and whileBlock.getAStmt() = s |
    result = getStmtId(ws)
  )
  or
  // Оператор внутри BlockStmt который является телом for
  exists(BlockStmt forBlock, ForStmt fs |
    forBlock = fs.getStmt() and forBlock.getAStmt() = s |
    result = getStmtId(fs)
  )
  or
  // Оператор внутри BlockStmt который является телом do-while
  exists(BlockStmt doBlock, DoStmt ds |
    doBlock = ds.getStmt() and doBlock.getAStmt() = s |
    result = getStmtId(ds)
  )
}

/** Тип ветви: then / else / body / пусто */
string getBranchType(Stmt s) {
  // Прямой потомок then-ветви if (один оператор без BlockStmt)
  exists(IfStmt ifs | ifs.getThen() = s | result = "then")
  or
  // Прямой потомок else-ветви if
  exists(IfStmt ifs | ifs.getElse() = s | result = "else")
  or
  // Прямой потомок тела while
  exists(WhileStmt ws | ws.getStmt() = s | result = "body")
  or
  // Прямой потомок тела for
  exists(ForStmt fs | fs.getStmt() = s | result = "body")
  or
  // Прямой потомок тела do-while
  exists(DoStmt ds | ds.getStmt() = s | result = "body")
  or
  // Первый оператор внутри BlockStmt then-ветви
  exists(IfStmt ifs |
    exists(BlockStmt thenBlock | ifs.getThen() = thenBlock |
      s = thenBlock.getAStmt()
    ) |
    result = "then"
  )
  or
  // Первый оператор внутри BlockStmt else-ветви
  exists(IfStmt ifs |
    exists(BlockStmt elseBlock | ifs.getElse() = elseBlock |
      s = elseBlock.getAStmt()
    ) |
    result = "else"
  )
  or
  // Первый оператор внутри BlockStmt тела while
  exists(WhileStmt ws |
    exists(BlockStmt whileBlock | ws.getStmt() = whileBlock |
      s = whileBlock.getAStmt()
    ) |
    result = "body"
  )
  or
  // Первый оператор внутри BlockStmt тела for
  exists(ForStmt fs |
    exists(BlockStmt forBlock | fs.getStmt() = forBlock |
      s = forBlock.getAStmt()
    ) |
    result = "body"
  )
  or
  // Первый оператор внутри BlockStmt тела do-while
  exists(DoStmt ds |
    exists(BlockStmt doBlock | ds.getStmt() = doBlock |
      s = doBlock.getAStmt()
    ) |
    result = "body"
  )
  or
  // Второй+ оператор внутри BlockStmt then-ветви
  exists(IfStmt ifs |
    exists(BlockStmt thenBlock | ifs.getThen() = thenBlock |
      s = thenBlock.getAStmt().getNextStmt()
    ) |
    result = "then"
  )
  or
  // Второй+ оператор внутри BlockStmt else-ветви
  exists(IfStmt ifs |
    exists(BlockStmt elseBlock | ifs.getElse() = elseBlock |
      s = elseBlock.getAStmt().getNextStmt()
    ) |
    result = "else"
  )
  or
  // Второй+ оператор внутри BlockStmt тела while
  exists(WhileStmt ws |
    exists(BlockStmt whileBlock | ws.getStmt() = whileBlock |
      s = whileBlock.getAStmt().getNextStmt()
    ) |
    result = "body"
  )
  or
  // Второй+ оператор внутри BlockStmt тела for
  exists(ForStmt fs |
    exists(BlockStmt forBlock | fs.getStmt() = forBlock |
      s = forBlock.getAStmt().getNextStmt()
    ) |
    result = "body"
  )
  or
  // Второй+ оператор внутри BlockStmt тела do-while
  exists(DoStmt ds |
    exists(BlockStmt doBlock | ds.getStmt() = doBlock |
      s = doBlock.getAStmt().getNextStmt()
    ) |
    result = "body"
  )
  or
  result = ""
}

from Function f, Stmt s
where
  f.hasDefinition() and
  isProjectFile(f.getFile()) and
  s.getEnclosingFunction() = f and
  (
    s instanceof IfStmt or
    s instanceof WhileStmt or
    s instanceof ForStmt or
    s instanceof DoStmt or
    s instanceof ReturnStmt or
    s instanceof ExprStmt
  )
select
  f.getQualifiedName() as func_name,
  getStmtId(s) as stmt_id,
  s.getLocation().getStartLine() as line,
  s.getLocation().getEndLine() as line_end,
  getStmtType(s) as stmt_type,
  getStmtLabel(s) as stmt_label,
  getParentId(s) as parent_id,
  getBranchType(s) as branch_type
order by func_name, line
