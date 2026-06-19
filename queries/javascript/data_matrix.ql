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

/** Квалифицированное имя переменной по её VarDecl */
string varQnameFromDecl(VarDecl vd) {
  exists(Function f | f = vd.getEnclosingFunction() and exists(qname(f)) |
    result = qname(f) + "." + vd.getName()
  )
  or
  not exists(Function f | f = vd.getEnclosingFunction()) and
  result = vd.getFile().getBaseName() + "." + vd.getName()
}

predicate isWriteAccess(VarAccess va) {
  exists(AssignExpr a | a.getLhs() = va)
  or
  exists(UpdateExpr u | u.getOperand() = va)
  or
  exists(CompoundAssignExpr ca | ca.getLhs() = va)
}

string getAccessType(VarAccess va) {
  exists(InvokeExpr call | call.getAnArgument() = va) and result = "аргумент"
  or
  not exists(InvokeExpr call | call.getAnArgument() = va) and
  isWriteAccess(va) and
  result = "запись"
  or
  not exists(InvokeExpr call | call.getAnArgument() = va) and
  not isWriteAccess(va) and
  result = "чтение"
}

from Function f, VarAccess va, VarDecl vd
where
  isProjectFile(f.getFile()) and
  va.getEnclosingFunction() = f and
  va.getVariable() = vd.getVariable() and
  vd.getVariable() instanceof LocalVariable and
  isProjectFile(vd.getFile()) and
  exists(qname(f)) and
  exists(varQnameFromDecl(vd))
select
  qname(f) as function_name,
  varQnameFromDecl(vd) as variable_name,
  va.getFile().getAbsolutePath() as func_file,
  va.getLocation().getStartLine() as access_line,
  getAccessType(va) as access_type
order by variable_name, function_name
