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

/** Квалифицированное имя переменной (совпадает с info_objects.ql) */
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

/** Файл переменной */
File varFile(Variable v) {
  result = v.getScope().(Function).getLocation().getFile()
  or
  result = v.getScope().(Module).getFile()
  or
  result = v.getScope().(Class).getLocation().getFile()
}

/**
 * Запись: Name стоит в левой части присваивания или является целью цикла/with.
 * Name.isStore() отсутствует в Python CodeQL 7.x — определяем через контекст.
 */
predicate isWriteContext(Name n) {
  exists(Assign a | a.getATarget() = n)
  or
  exists(Assign a | a.getATarget().(Tuple).getAnElt() = n)
  or
  exists(AugAssign a | a.getTarget() = n)
  or
  exists(For f | f.getTarget() = n)
  or
  exists(For f | f.getTarget().(Tuple).getAnElt() = n)
}

/** Признак передачи переменной в качестве аргумента вызова */
predicate isArgContext(Name n) {
  exists(Call c | c.getAnArg() = n)
}

/**
 * Тип обращения к переменной:
 *   аргумент — передаётся как аргумент вызова (высший приоритет);
 *   запись   — левая часть присваивания / цель цикла;
 *   чтение   — все остальные обращения.
 */
string getAccessType(Name n) {
  isArgContext(n) and result = "аргумент"
  or
  not isArgContext(n) and isWriteContext(n) and result = "запись"
  or
  not isArgContext(n) and not isWriteContext(n) and result = "чтение"
}

from Function f, Name n, Variable v
where
  n.getScope() = f and
  n.getVariable() = v and
  f.getName() != "" and
  v.getId() != "" and
  isProjectFile(f.getLocation().getFile()) and
  isProjectFile(varFile(v)) and
  exists(varQname(v))
select
  f.getQualifiedName() as function_name,
  varQname(v) as variable_name,
  n.getLocation().getFile().getAbsolutePath() as func_file,
  n.getLocation().getStartLine() as access_line,
  getAccessType(n) as access_type
order by variable_name, function_name, access_line
