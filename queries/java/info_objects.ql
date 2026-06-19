import java

predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}")
}

string qname(Callable c) {
  result = c.getDeclaringType().getQualifiedName() + "." + c.getName()
}

/**
 * Имя переменной (ключ ИО). Должно совпадать с data_matrix.ql / arg_flow.ql:
 *   поле        → <Тип>.<имя>
 *   локальная/параметр → <Тип>.<метод>.<имя>
 */
string varName(Variable v) {
  exists(Field f | f = v | result = f.getDeclaringType().getQualifiedName() + "." + f.getName())
  or
  exists(LocalScopeVariable lv | lv = v | result = qname(lv.getCallable()) + "." + lv.getName())
}

/** Файл, в котором объявлена переменная. */
File varFile(Variable v) {
  result = v.(Field).getFile()
  or
  result = v.(LocalScopeVariable).getCallable().getFile()
}

/** Строка объявления переменной. */
int varLine(Variable v) {
  result = v.(Field).getLocation().getStartLine()
  or
  result = v.(LocalScopeVariable).getLocation().getStartLine()
}

/** Тип ИО как строка (аналог C++ getVarKind). */
string getVarKind(Variable v) {
  v instanceof Parameter and result = "parameter"
  or
  v instanceof Field and v.isStatic() and result = "static field"
  or
  v instanceof Field and not v.isStatic() and result = "field"
  or
  v instanceof LocalVariableDecl and result = "local variable"
}

from Variable v
where
  isProjectFile(varFile(v)) and
  (
    v instanceof Field or
    v instanceof LocalScopeVariable
  )
select
  varName(v) as qualified_name,
  v.getName() as name,
  v.getType().getName() as type,
  varFile(v).getAbsolutePath() as file,
  varLine(v) as line,
  getVarKind(v) as kind
order by file, line
