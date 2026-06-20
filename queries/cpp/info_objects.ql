import cpp

/** Определяем тип переменной как строку */
string getVariableKind(Variable v) {
  v instanceof Parameter and result = "parameter"
  or
  v instanceof LocalScopeVariable and not v instanceof Parameter and result = "local variable"
  or
  v instanceof GlobalVariable and v.isStatic() and result = "static global variable"
  or
  v instanceof GlobalVariable and not v.isStatic() and result = "global variable"
  or
  v instanceof MemberVariable and v.isStatic() and result = "static field"
  or
  v instanceof MemberVariable and not v.isStatic() and result = "field"
  or
  not v instanceof Parameter and not v instanceof LocalScopeVariable and not v instanceof GlobalVariable and not v instanceof MemberVariable and result = "variable"
}

/** Файл принадлежит тестовому проекту */
predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}") and
  file.getExtension() = ["cpp", "c", "h", "hpp"] and not file.getAbsolutePath().matches("%CMakeFiles%") and not file.getAbsolutePath().matches("%/usr/include%") and not file.getAbsolutePath().matches("%/usr/lib%") and not file.getAbsolutePath().matches("%/lib/%") and not file.getAbsolutePath().matches("%.moc%") and not file.getAbsolutePath().matches("%.rcc%") and not file.getAbsolutePath().matches("%.ui%") and not file.getAbsolutePath().matches("%.._._%")
}

/**
 * Имя переменной для перечня ИО. У глобальных переменных и полей классов есть
 * getQualifiedName(); у локальных переменных и параметров его нет, поэтому
 * синтезируем "<функция>::<имя>", чтобы ключ был стабильным и совпадал между
 * запросами (info_objects / data_matrix).
 */
string varName(Variable v) {
  exists(v.getQualifiedName()) and result = v.getQualifiedName()
  or
  not exists(v.getQualifiedName()) and
  result = v.(LocalScopeVariable).getFunction().getQualifiedName() + "::" + v.getName()
}

from Variable v
where isProjectFile(v.getFile())
select
  varName(v) as qualified_name,
  v.getName() as name,
  v.getType().getName() as type_name,
  v.getFile().getAbsolutePath() as file,
  v.getLocation().getStartLine() as line,
  getVariableKind(v) as kind
order by file, line, qualified_name
