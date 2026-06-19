import python

/** Файл принадлежит тестовому проекту Python */
predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}") and
  file.getExtension() = "py" and
  not file.getAbsolutePath().matches("%site-packages%") and
  not file.getAbsolutePath().matches("%__pycache__%") and
  not file.getAbsolutePath().matches("%.venv%") and
  not file.getAbsolutePath().matches("%/venv/%") and
  not file.getAbsolutePath().matches("%\\venv\\%")
}

/**
 * Прямой вызов: foo() — callee определяется по имени.
 * Метод: self.method() / obj.method() — совпадение по имени среди методов.
 */
predicate callsFunction(Call c, Function caller, Function callee) {
  // Прямой вызов функции: foo(...)
  c.getScope() = caller and
  c.getFunc().(Name).getId() = callee.getName() and
  not callee.isMethod() and
  isProjectFile(callee.getLocation().getFile())
  or
  // Вызов метода: obj.method(...)
  c.getScope() = caller and
  c.getFunc().(Attribute).getName() = callee.getName() and
  callee.isMethod() and
  isProjectFile(callee.getLocation().getFile())
}

from Call c, Function caller, Function callee
where
  callsFunction(c, caller, callee) and
  caller != callee and
  caller.getName() != "" and
  isProjectFile(caller.getLocation().getFile())
select
  caller.getQualifiedName() as caller_name,
  callee.getQualifiedName() as callee_name,
  caller.getLocation().getFile().getAbsolutePath() as caller_file,
  // Файл объявления callee (как `file` в functional_objects.ql)
  callee.getLocation().getFile().getAbsolutePath() as callee_file,
  c.getLocation().getStartLine() as call_line
order by callee_name, caller_name, call_line
