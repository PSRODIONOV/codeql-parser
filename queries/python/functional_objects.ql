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

/** Тип функционального объекта */
string getFunctionKind(Function f) {
  f.getName() = "__init__" and result = "constructor"
  or
  f.getName() = "main" and result = "entry point"
  or
  f.isMethod() and not f.getName() = "__init__" and result = "member function"
  or
  not f.isMethod() and not f.getName() = "__init__" and not f.getName() = "main" and
  result = "function"
}

/** Имя родительского класса или "(global)" для модульных функций */
string getParentTypeName(Function f) {
  f.isMethod() and result = f.getScope().(Class).getName()
  or
  not f.isMethod() and result = "(global)"
}

from Function f
where
  isProjectFile(f.getLocation().getFile()) and
  f.getName() != "" and
  exists(getFunctionKind(f))
select
  f.getQualifiedName() as qualified_name,
  f.getName() as name,
  getParentTypeName(f) as parent_type,
  f.getLocation().getFile().getAbsolutePath() as file,
  f.getLocation().getStartLine() as line,
  getFunctionKind(f) as kind
order by file, line, qualified_name
