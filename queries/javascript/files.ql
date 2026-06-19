import javascript

predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}") and
  not file.getAbsolutePath().matches("%test-project-js-db%") and
  not file.getAbsolutePath().matches("%node_modules%")
}

from File f
where
  isProjectFile(f) and
  f.getExtension() = ["js", "mjs", "ts"]
select
  f.getAbsolutePath() as abs_path,
  f.getBaseName() as base_name
order by abs_path
