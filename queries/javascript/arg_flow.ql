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

string varQnameFromDecl(VarDecl vd) {
  exists(Function f | f = vd.getEnclosingFunction() and exists(qname(f)) |
    result = qname(f) + "." + vd.getName()
  )
  or
  not exists(Function f | f = vd.getEnclosingFunction()) and
  result = vd.getFile().getBaseName() + "." + vd.getName()
}

from DataFlow::CallNode call, Function caller, Function callee,
     VarAccess argAccess, VarDecl argDecl, Parameter param, int i
where
  caller = call.getEnclosingFunction() and
  callee = call.getACallee() and
  isProjectFile(caller.getFile()) and
  isProjectFile(callee.getFile()) and
  call.asExpr().(InvokeExpr).getArgument(i) = argAccess and
  argDecl.getVariable() = argAccess.getVariable() and
  argDecl.getVariable() instanceof LocalVariable and
  param = callee.getParameter(i) and
  exists(qname(caller)) and
  exists(qname(callee)) and
  exists(varQnameFromDecl(argDecl))
select
  qname(caller) as caller_name,
  qname(callee) as callee_name,
  varQnameFromDecl(argDecl) as caller_var,
  qname(callee) + "." + param.getName() as param_var,
  caller.getFile().getBaseName() as caller_file,
  call.getStartLine() as call_line
order by caller_name, callee_name, call_line
