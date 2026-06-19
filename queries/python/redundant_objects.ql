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
 * Функция считается избыточной (неиспользуемой), если нет ни одного Call,
 * ссылающегося на неё по имени.
 * Исключения: main, __init__, __main__, специальные методы (__str__, __repr__ и др.),
 * entry-point функции и методы, вызываемые как переопределения (callback/virtual).
 */
from Function f
where
  isProjectFile(f.getLocation().getFile()) and
  f.getName() != "" and
  not f.getName() = "main" and
  not f.getName().matches("__%") and   // Исключаем все dunder-методы
  not exists(Call c |
    c.getFunc().(Name).getId() = f.getName() or
    c.getFunc().(Attribute).getName() = f.getName()
  )
select
  f.getQualifiedName() as qualified_name,
  f.getName() as name,
  f.getLocation().getFile().getBaseName() as file,
  f.getLocation().getStartLine() as line
order by file, line
