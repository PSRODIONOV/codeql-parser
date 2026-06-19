import python

/** Файл принадлежит тестовому проекту Python */
predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}") and
  file.getExtension() = "py" and
  not file.getAbsolutePath().matches("%site-packages%") and
  not file.getAbsolutePath().matches("%__pycache__%") and
  not file.getAbsolutePath().matches("%.venv%") and
  not file.getAbsolutePath().matches("%/venv/%") and
  not file.getAbsolutePath().matches("%\\venv\\%")
}

/**
 * Обращения к файлам через built-in open() и io.open().
 * Фиксируем функции, которые открывают файл с литеральным именем.
 * Режим ("r","w","a" и т.д.) берётся из второго аргумента, если он строка.
 */
from Function f, Call openCall, StringLiteral fileName
where
  isProjectFile(f.getLocation().getFile()) and
  openCall.getScope() = f and
  (
    openCall.getFunc().(Name).getId() = "open"
    or
    openCall.getFunc().(Attribute).getName() = "open" and
    openCall.getFunc().(Attribute).getObject().(Name).getId() = "io"
    or
    openCall.getFunc().(Attribute).getName() = "open" and
    openCall.getFunc().(Attribute).getObject().(Name).getId() = "codecs"
  ) and
  openCall.getArg(0) = fileName
select
  f.getQualifiedName() as function_name,
  f.getLocation().getFile().getAbsolutePath() as func_file,
  fileName.getText() as file_name,
  "файловый ввод-вывод" as access_type,
  openCall.getLocation().getStartLine() as access_line
order by file_name, function_name
