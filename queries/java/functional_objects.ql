import java

/** Файл принадлежит тестовому проекту Java. */
predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}")
}

/** Полное имя ФО: <Тип>.<метод> (аналог C++ getQualifiedName). */
string qname(Callable c) {
  result = c.getDeclaringType().getQualifiedName() + "." + c.getName()
}

/** Имя родительского типа. */
string getParentTypeName(Callable c) { result = c.getDeclaringType().getName() }

/** Тип ФО как строка. */
string getCallableKind(Callable c) {
  c instanceof Constructor and result = "constructor"
  or
  c.getName() = "main" and result = "entry point"
  or
  c instanceof Method and not c.getName() = "main" and result = "member function"
}

// Геометрия вставки датчика входа/выхода тела функции.
//
// Конструктор с явным super()/this() — вставка ПОСЛЕ него, а не после '{'
// (см. explicitCtorCall ниже). Неявный (сгенерированный) super() имеет
// вырожденную локацию на строке сигнатуры — его учитывать нельзя.
predicate explicitCtorCall(BlockStmt b, Stmt first) {
  first = b.getStmt(0) and
  (first instanceof SuperConstructorInvocationStmt or first instanceof ThisConstructorInvocationStmt) and
  (
    first.getLocation().getStartLine() > b.getLocation().getStartLine()
    or
    first.getLocation().getStartLine() = b.getLocation().getStartLine() and
    first.getLocation().getStartColumn() > b.getLocation().getStartColumn()
  )
}

int insLine(Callable c, BlockStmt body) {
  exists(Stmt first | explicitCtorCall(body, first) and result = first.getLocation().getEndLine())
  or
  not explicitCtorCall(body, _) and result = body.getLocation().getStartLine()
}

int insCol(Callable c, BlockStmt body) {
  exists(Stmt first | explicitCtorCall(body, first) and result = first.getLocation().getEndColumn())
  or
  not explicitCtorCall(body, _) and result = body.getLocation().getStartColumn()
}

from Callable c, BlockStmt body
where
  isProjectFile(c.getFile()) and
  body = c.getBody() and
  c.fromSource() and
  // Исключаем синтетические инициализаторы <clinit> (статический) и
  // <obinit> (инстансный) — это не пользовательские процедуры/функции.
  not c instanceof InitializerMethod and
  // Исключаем сгенерированные дефолтные конструкторы — нет тела в исходнике.
  not c.(Constructor).isDefaultConstructor() and
  // Исключаем синтетические методы лямбд и method reference — их «тело»
  // выражение, обёртка датчиком ломает синтаксис.
  not exists(FunctionalExpr fe | fe.asMethod() = c)
select
  qname(c) as qualified_name,
  c.getName() as name,
  getParentTypeName(c) as parent_type,
  c.getFile().getAbsolutePath() as file,
  c.getLocation().getStartLine() as line,
  getCallableKind(c) as kind,
  insLine(c, body) as ins_line,
  insCol(c, body) as ins_col,
  body.getLocation().getEndLine() as end_line,
  body.getLocation().getEndColumn() as end_col
order by file, line, qualified_name
