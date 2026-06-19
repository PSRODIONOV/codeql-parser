import java

predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}")
}

from File f
where
  isProjectFile(f) and
  exists(Callable c | c.getFile() = f and c.fromSource())
select
  f.getAbsolutePath() as abs_path,
  f.getBaseName() as base_name
order by abs_path
