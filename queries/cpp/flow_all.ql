import cpp
from Function f, Stmt s
where
  f.hasDefinition() and
  s.getEnclosingFunction() = f and
  not s instanceof BlockStmt and
  not s instanceof EmptyStmt
select
  f.getQualifiedName() as func_name,
  s.getFile().getBaseName() as file,
  s.getLocation().getStartLine() as line
order by func_name, line
