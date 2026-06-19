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

/** Квалифицированное имя переменной (совпадает с info_objects.ql / data_matrix.ql) */
string varQname(Variable v) {
  v.getScope() instanceof Function and
  result = v.getScope().(Function).getQualifiedName() + "." + v.getId()
  or
  v.getScope() instanceof Module and
  result = v.getScope().(Module).getName() + "." + v.getId()
  or
  v.getScope() instanceof Class and
  result = v.getScope().(Class).getQualifiedName() + "." + v.getId()
}

/**
 * Поток аргумент→параметр: для каждого вызова фиксируем,
 * какая переменная-аргумент передаётся в какой параметр.
 */
from
  Function caller, Call c, Function callee,
  Name argName, Variable argVar, int i
where
  c.getScope() = caller and
  caller.getName() != "" and
  isProjectFile(caller.getLocation().getFile()) and
  (
    c.getFunc().(Name).getId() = callee.getName() and not callee.isMethod()
    or
    c.getFunc().(Attribute).getName() = callee.getName() and callee.isMethod()
  ) and
  isProjectFile(callee.getLocation().getFile()) and
  callee.getName() != "" and
  c.getArg(i) = argName and
  argName.getVariable() = argVar and
  exists(callee.getArg(i)) and
  exists(varQname(argVar))
select
  caller.getQualifiedName() as caller_name,
  callee.getQualifiedName() as callee_name,
  varQname(argVar) as caller_var,
  callee.getQualifiedName() + "." + callee.getArg(i) as param_var,
  caller.getLocation().getFile().getBaseName() as caller_file,
  c.getLocation().getStartLine() as call_line
order by caller_name, callee_name, call_line
