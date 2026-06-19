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

/** Квалифицированное имя переменной (getId() — правильный метод Python Variable) */
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

/** Файл переменной через её область видимости */
File varFile(Variable v) {
  result = v.getScope().(Function).getLocation().getFile()
  or
  result = v.getScope().(Module).getFile()
  or
  result = v.getScope().(Class).getLocation().getFile()
}

/**
 * Строка первого использования переменной (любого обращения).
 * В Python нет явных объявлений — берём минимальную строку использования.
 */
int varLine(Variable v) {
  result = min(Name n | n.getVariable() = v | n.getLocation().getStartLine())
  or
  not exists(Name n | n.getVariable() = v) and
  result = v.getScope().(Function).getLocation().getStartLine()
}

/** Тип информационного объекта */
string varKind(Variable v) {
  v instanceof LocalVariable and result = "local variable"
  or
  v instanceof GlobalVariable and result = "global variable"
}

from Variable v
where
  isProjectFile(varFile(v)) and
  exists(varQname(v)) and
  v.getId() != "" and
  not v.getId() = "_" and
  // Имена функций/классов — это ФО, не ИО: в Python def/class создают Variable
  not exists(Function f | f.getEnclosingScope() = v.getScope() and f.getName() = v.getId()) and
  not exists(Class c | c.getEnclosingScope() = v.getScope() and c.getName() = v.getId())
select
  varQname(v) as qualified_name,
  v.getId() as name,
  "" as type_name,
  varFile(v).getAbsolutePath() as file,
  varLine(v) as line,
  varKind(v) as kind
order by file, line, qualified_name
