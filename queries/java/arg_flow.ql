import java

predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}")
}

string qname(Callable c) {
  result = c.getDeclaringType().getQualifiedName() + "." + c.getName()
}

string varName(Variable v) {
  exists(Field f | f = v | result = f.getDeclaringType().getQualifiedName() + "." + f.getName())
  or
  exists(LocalScopeVariable lv | lv = v | result = qname(lv.getCallable()) + "." + lv.getName())
}

/**
 * Аргумент→параметр: для каждого вызова фиксируем, какая переменная-аргумент
 * передаётся в какой параметр вызываемого метода. Захватываем только прямые
 * VarAccess в позиции аргумента, чтобы ключи ИО совпадали с info_objects.ql.
 */
from Callable caller, Call call, VarAccess argAccess, Variable argVar, Parameter param, int i
where
  call.getCaller() = caller and
  call.getArgument(i) = argAccess and
  argAccess.getVariable() = argVar and
  param = call.getCallee().getParameter(i) and
  isProjectFile(caller.getFile()) and
  (argVar instanceof Field or argVar instanceof LocalScopeVariable) and
  isProjectFile(call.getCallee().getFile())
select
  qname(caller) as caller_name,
  qname(call.getCallee()) as callee_name,
  varName(argVar) as caller_var,
  varName(param) as param_var,
  caller.getFile().getBaseName() as caller_file,
  call.getLocation().getStartLine() as call_line
order by caller_name, callee_name, call_line
