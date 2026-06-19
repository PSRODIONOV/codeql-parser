import cpp

/** Файл принадлежит тестовому проекту */
predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}") and
  file.getExtension() = ["cpp", "c", "h", "hpp"] and not file.getAbsolutePath().matches("%CMakeFiles%") and not file.getAbsolutePath().matches("%/usr/include%") and not file.getAbsolutePath().matches("%/usr/lib%") and not file.getAbsolutePath().matches("%/lib/%") and not file.getAbsolutePath().matches("%.moc%") and not file.getAbsolutePath().matches("%.rcc%") and not file.getAbsolutePath().matches("%.ui%") and not file.getAbsolutePath().matches("%.._._%")
}

/**
 * Имя переменной (ключ ИО). Должно совпадать с info_objects.ql: для локальных
 * переменных и параметров getQualifiedName() пуст — синтезируем "<функция>::<имя>".
 */
string varName(Variable v) {
  exists(v.getQualifiedName()) and result = v.getQualifiedName()
  or
  not exists(v.getQualifiedName()) and
  result = v.(LocalScopeVariable).getFunction().getQualifiedName() + "::" + v.getName()
}

/**
 * Запись в собственную память переменной. В отличие от va.isLValue(), который
 * помечает lvalue ВСЮ цепочку доступа (включая базу массива и квалификатор перед
 * разыменованием указателя), это правило считает записью только модификацию
 * памяти самой переменной:
 *   - прямое присваивание / составное присваивание / ++ / --  (x = .., x += .., x++);
 *   - запись в .поле или элемент[i] массива той же переменной  (x.f = .., buf[i] = ..).
 * Доступ ЧЕРЕЗ разыменование указателя (p->f = .., (*p) = .., ptr[i]->f = ..)
 * читает указатель, а пишет в чужой объект — поэтому это «чтение».
 */
predicate sameObjectLValue(VariableAccess va, Expr e) {
  e = va
  or
  exists(DotFieldAccess fa | fa = e and sameObjectLValue(va, fa.getQualifier()))
  or
  exists(ArrayExpr ae |
    ae = e and sameObjectLValue(va, ae.getArrayBase()) and
    ae.getArrayBase().getType().getUnspecifiedType() instanceof ArrayType)
}

predicate isWrite(VariableAccess va) {
  exists(Assignment a | sameObjectLValue(va, a.getLValue()))
  or
  exists(CrementOperation c | sameObjectLValue(va, c.getOperand()))
}

/**
 * Тип обращения к переменной:
 *   аргумент — переменная передаётся как аргумент вызова (наивысший приоритет);
 *   запись   — модификация собственной памяти переменной (см. isWrite);
 *   чтение   — все остальные обращения.
 */
string getAccessType(VariableAccess va) {
  exists(Call c | c.getAnArgument() = va) and result = "аргумент"
  or
  not exists(Call c | c.getAnArgument() = va) and isWrite(va) and result = "запись"
  or
  not exists(Call c | c.getAnArgument() = va) and not isWrite(va) and result = "чтение"
}

from Function f, Variable v, VariableAccess va
where
  va.getEnclosingFunction() = f and
  va.getTarget() = v and
  (
    v instanceof LocalScopeVariable or
    v instanceof GlobalVariable or
    v instanceof MemberVariable or
    v instanceof Parameter
  ) and
  isProjectFile(f.getFile()) and
  isProjectFile(v.getFile())
select
  f.getQualifiedName() as function_name,
  varName(v) as variable_name,
  f.getFile().getAbsolutePath() as func_file,
  va.getLocation().getStartLine() as access_line,
  getAccessType(va) as access_type
order by variable_name, function_name, access_line
