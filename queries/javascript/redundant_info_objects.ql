import javascript

predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}") and
  not file.getAbsolutePath().matches("%test-project-js-db%") and
  not file.getAbsolutePath().matches("%node_modules%")
}

// Переменные уровня модуля, к которым нет ни одного обращения
from VarDecl vd
where
  isProjectFile(vd.getFile()) and
  vd.getVariable() instanceof LocalVariable and
  not exists(Function f | f = vd.getEnclosingFunction()) and
  not exists(VarAccess va | va.getVariable() = vd.getVariable())
select
  vd.getFile().getBaseName() + "." + vd.getName() as qualified_name,
  vd.getName() as name,
  vd.getFile().getAbsolutePath() as file,
  vd.getLocation().getStartLine() as line
order by file, line
