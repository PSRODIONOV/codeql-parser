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
 * Запись без чтения: проверяем, что переменная нигде не читается (исключаем
 * только write-контекст — левая часть присваивания, цель цикла).
 * Name.isLoad() отсутствует в Python CodeQL 7.x — определяем как отсутствие записи.
 */
predicate isWriteContext(Name n) {
  exists(Assign a | a.getATarget() = n or a.getATarget().(Tuple).getAnElt() = n)
  or
  exists(AugAssign a | a.getTarget() = n)
  or
  exists(For f | f.getTarget() = n or f.getTarget().(Tuple).getAnElt() = n)
}

from Variable v
where
  isProjectFile(varFile(v)) and
  v.getId() != "" and
  not v.getId().matches("_%") and
  exists(varQname(v)) and
  // Нет ни одного не-write обращения (только write или вообще нет обращений)
  not exists(Name n | n.getVariable() = v and not isWriteContext(n))
select
  varQname(v) as qualified_name,
  v.getId() as name,
  varFile(v).getBaseName() as file,
  min(Name n | n.getVariable() = v | n.getLocation().getStartLine()) as line
order by file, line
