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

from Callable c
where
  isProjectFile(c.getFile()) and
  exists(c.getBody()) and
  c.fromSource() and
  // Исключаем синтетические инициализаторы <clinit> (статический) и
  // <obinit> (инстансный) — это не пользовательские процедуры/функции.
  not c instanceof InitializerMethod
select
  qname(c) as qualified_name,
  c.getName() as name,
  getParentTypeName(c) as parent_type,
  c.getFile().getAbsolutePath() as file,
  c.getLocation().getStartLine() as line,
  getCallableKind(c) as kind
order by file, line, qualified_name
