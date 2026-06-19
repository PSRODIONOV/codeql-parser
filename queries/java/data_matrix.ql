import java

predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}")
}

/** Полное имя ФО (должно совпадать с functional_objects.ql). */
string qname(Callable c) {
  result = c.getDeclaringType().getQualifiedName() + "." + c.getName()
}

/** Имя переменной (ключ ИО). Должно совпадать с info_objects.ql. */
string varName(Variable v) {
  exists(Field fld | fld = v |
    result = fld.getDeclaringType().getQualifiedName() + "." + fld.getName()
  )
  or
  exists(LocalScopeVariable lv | lv = v |
    result = qname(lv.getCallable()) + "." + lv.getName()
  )
}

/** Обращение является записью: левая часть присваивания или операнд ++/--. */
predicate isWriteAccess(VarAccess va) {
  exists(Assignment a | a.getDest() = va)
  or
  exists(UnaryAssignExpr u | u.getExpr() = va)
}

/**
 * Тип обращения к переменной:
 *   аргумент — переменная передаётся как аргумент вызова (высший приоритет);
 *   запись   — присваивание / инкремент;
 *   чтение   — прочие обращения.
 */
string getAccessType(VarAccess va) {
  va instanceof Argument and result = "аргумент"
  or
  not va instanceof Argument and isWriteAccess(va) and result = "запись"
  or
  not va instanceof Argument and not isWriteAccess(va) and result = "чтение"
}

from Callable f, Variable v, VarAccess va
where
  isProjectFile(f.getFile()) and
  va.getEnclosingCallable() = f and
  va.getVariable() = v and
  (v instanceof Field or v instanceof LocalScopeVariable) and
  // только ИО, объявленные в самом проекте (исключаем System.out и т.п.)
  (
    v instanceof LocalScopeVariable
    or
    isProjectFile(v.(Field).getDeclaringType().getFile())
  )
select
  qname(f) as function_name,
  varName(v) as variable_name,
  va.getFile().getAbsolutePath() as func_file,
  va.getLocation().getStartLine() as access_line,
  getAccessType(va) as access_type
order by variable_name, function_name
