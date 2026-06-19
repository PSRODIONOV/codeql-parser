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

from DataFlow::CallNode call, Function caller, Function callee
where
  caller = call.getEnclosingFunction() and
  callee = call.getACallee() and
  isProjectFile(caller.getFile()) and
  isProjectFile(callee.getFile()) and
  exists(qname(caller)) and
  exists(qname(callee))
select
  qname(caller) as caller_name,
  qname(callee) as callee_name,
  caller.getFile().getBaseName() as caller_file,
  call.getStartLine() as call_line
order by caller_name, callee_name, call_line
