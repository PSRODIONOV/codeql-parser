import java

predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}")
}

string qname(Callable c) {
  result = c.getDeclaringType().getQualifiedName() + "." + c.getName()
}

from Call call, Callable caller, Callable callee
where
  call.getCaller() = caller and
  call.getCallee() = callee and
  caller != callee and
  isProjectFile(caller.getFile()) and
  isProjectFile(callee.getFile())
select
  qname(caller) as caller_name,
  qname(callee) as callee_name,
  caller.getFile().getBaseName() as caller_file,
  call.getLocation().getStartLine() as call_line
order by callee_name, caller_name, call_line
