import java

predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}")
}

string varName(Variable v) {
  exists(Field f | f = v | result = f.getDeclaringType().getQualifiedName() + "." + f.getName())
}

from Field v
where
  isProjectFile(v.getFile()) and
  not exists(VarAccess va | va.getVariable() = v)
select
  varName(v) as qualified_name,
  v.getName() as name,
  v.getFile().getAbsolutePath() as file,
  v.getLocation().getStartLine() as line
order by file, line
