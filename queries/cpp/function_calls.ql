import cpp

from FunctionCall fc
where exists(fc.getTarget())
select
  fc.getTarget().getQualifiedName() as called_function,
  fc.getEnclosingFunction().getQualifiedName() as caller_name,
  fc.getEnclosingFunction().getFile().getBaseName() as caller_file,
  fc.getLocation().getStartLine() as call_line,
  fc.toString() as call_statement
