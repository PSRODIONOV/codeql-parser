import java

predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}")
}

string qname(Callable c) {
  result = c.getDeclaringType().getQualifiedName() + "." + c.getName()
}

from Callable c
where
  isProjectFile(c.getFile()) and
  exists(c.getBody()) and
  c.fromSource() and
  not exists(Call call | call.getCallee() = c) and
  not c.getName() = "main"
select
  qname(c) as qualified_name,
  c.getName() as name,
  c.getFile().getAbsolutePath() as file,
  c.getLocation().getStartLine() as line
order by file, line
