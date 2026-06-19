import cpp

/** Файл принадлежит тестовому проекту */
predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}") and
  file.getExtension() = ["cpp", "c", "h", "hpp"] and not file.getAbsolutePath().matches("%CMakeFiles%") and not file.getAbsolutePath().matches("%/usr/include%") and not file.getAbsolutePath().matches("%/usr/lib%") and not file.getAbsolutePath().matches("%/lib/%") and not file.getAbsolutePath().matches("%.moc%") and not file.getAbsolutePath().matches("%.rcc%") and not file.getAbsolutePath().matches("%.ui%") and not file.getAbsolutePath().matches("%.._._%")
}

/**
 * Имя переменной (ключ ИО). Должно совпадать с info_objects.ql / data_matrix.ql:
 * для локальных переменных и параметров getQualifiedName() пуст — синтезируем
 * "<функция>::<имя>".
 */
string varName(Variable v) {
  exists(v.getQualifiedName()) and result = v.getQualifiedName()
  or
  not exists(v.getQualifiedName()) and
  result = v.(LocalScopeVariable).getFunction().getQualifiedName() + "::" + v.getName()
}

/**
 * Аргумент→параметр: для каждого вызова функции фиксируем,
 * какая переменная-аргумент (из контекста вызывающей функции)
 * передаётся в какой параметр вызываемой функции.
 * Захватываем только прямые VariableAccess в позиции аргумента
 * (не вложенные выражения), чтобы ключи ИО совпадали с info_objects.ql.
 */
from
  Function caller, FunctionCall call,
  VariableAccess argAccess, Variable argVar,
  Parameter param, int i
where
  call.getEnclosingFunction() = caller and
  call.getArgument(i) = argAccess and
  argAccess.getTarget() = argVar and
  param = call.getTarget().getParameter(i) and
  isProjectFile(caller.getFile()) and
  isProjectFile(argVar.getFile()) and
  isProjectFile(call.getTarget().getFile())
select
  caller.getQualifiedName() as caller_name,
  call.getTarget().getQualifiedName() as callee_name,
  varName(argVar) as caller_var,
  varName(param) as param_var,
  caller.getFile().getBaseName() as caller_file,
  call.getLocation().getStartLine() as call_line
order by caller_name, callee_name, call_line
