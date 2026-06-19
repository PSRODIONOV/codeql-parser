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

from Function f
where
  isProjectFile(f.getFile()) and
  exists(f.getBody()) and
  exists(qname(f)) and
  not exists(DataFlow::CallNode call | call.getACallee() = f) and
  not f.getName() = "main" and
  f.getName() != ""
select
  qname(f) as qualified_name,
  f.getName() as name,
  f.getFile().getAbsolutePath() as file,
  f.getLocation().getStartLine() as line
order by file, line
