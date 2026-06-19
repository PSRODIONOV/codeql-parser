import javascript

predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}") and
  not file.getAbsolutePath().matches("%test-project-js-db%") and
  not file.getAbsolutePath().matches("%node_modules%")
}

string qname(Function f) {
  exists(MethodDefinition md | md.getBody() = f and md.getName() != "constructor" |
    result = md.getDeclaringClass().getName() + "." + md.getName()
  )
  or
  exists(MethodDefinition md | md.getBody() = f and md.getName() = "constructor" |
    result = md.getDeclaringClass().getName() + ".constructor"
  )
  or
  not exists(MethodDefinition md | md.getBody() = f) and
  f.getName() != "" and
  result = f.getName()
}

/**
 * Все информационные объекты проекта: параметры, локальные
 * переменные и переменные уровня модуля.
 */
predicate infoObject(
  string qualifiedName, string name, string file, int line, string kind
) {
  // Параметры функций
  exists(Function f, Parameter p |
    isProjectFile(f.getFile()) and
    p = f.getAParameter() and
    exists(qname(f)) and
    qualifiedName = qname(f) + "." + p.getName() and
    name = p.getName() and
    file = p.getLocation().getFile().getAbsolutePath() and
    line = p.getLocation().getStartLine() and
    kind = "parameter"
  )
  or
  // Локальные переменные внутри функций (не параметры, не self-reference функции)
  exists(VarDecl vd, Function f |
    isProjectFile(vd.getFile()) and
    f = vd.getEnclosingFunction() and
    vd.getVariable() instanceof LocalVariable and
    not exists(Parameter p | p = f.getAParameter() and p.getName() = vd.getName()) and
    // Исключаем self-reference: function foo(){} создаёт VarDecl 'foo' внутри foo
    not (vd.getName() = f.getName()) and
    exists(qname(f)) and
    qualifiedName = qname(f) + "." + vd.getName() and
    name = vd.getName() and
    file = vd.getFile().getAbsolutePath() and
    line = vd.getLocation().getStartLine() and
    kind = "local variable"
  )
  or
  // Переменные уровня модуля (исключаем ФО и классы)
  exists(VarDecl vd |
    isProjectFile(vd.getFile()) and
    not exists(Function f | f = vd.getEnclosingFunction()) and
    vd.getVariable() instanceof LocalVariable and
    // Исключаем имена функций-объявлений
    not exists(Function f |
      isProjectFile(f.getFile()) and
      f.getName() = vd.getName() and
      f.getFile() = vd.getFile()
    ) and
    // Исключаем имена классов
    not exists(ClassDefinition cd |
      isProjectFile(cd.getFile()) and
      cd.getName() = vd.getName() and
      cd.getFile() = vd.getFile()
    ) and
    qualifiedName = vd.getFile().getAbsolutePath() + "." + vd.getName() and
    name = vd.getName() and
    file = vd.getFile().getAbsolutePath() and
    line = vd.getLocation().getStartLine() and
    kind = "module variable"
  )
}

from string qn, string nm, string fl, int ln, string kd
where infoObject(qn, nm, fl, ln, kd)
select
  qn as qualified_name,
  nm as name,
  fl as file,
  ln as line,
  kd as kind
order by file, line
