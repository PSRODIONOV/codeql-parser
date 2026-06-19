import cpp

/** Файл принадлежит тестовому проекту (исходники, не артефакты сборки) */
predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}") and
  file.getExtension() = ["cpp", "c", "h", "hpp"] and not file.getAbsolutePath().matches("%CMakeFiles%") and not file.getAbsolutePath().matches("%/usr/include%") and not file.getAbsolutePath().matches("%/usr/lib%") and not file.getAbsolutePath().matches("%/lib/%") and not file.getAbsolutePath().matches("%.moc%") and not file.getAbsolutePath().matches("%.rcc%") and not file.getAbsolutePath().matches("%.ui%") and not file.getAbsolutePath().matches("%.._._%") and
  not file.getAbsolutePath().matches("%/build/%") and
  not file.getAbsolutePath().matches("%\\build\\%")
}

/** Исходный файл C/C++ (translation unit или заголовок) */
predicate isSourceFile(File f) {
  f.getExtension() = ["cpp", "cc", "cxx", "c", "h", "hpp", "hxx", "hh"]
}

from File f
where
  isProjectFile(f) and
  isSourceFile(f) and
  exists(Element e | e.getFile() = f)
select
  f.getAbsolutePath() as abs_path,
  f.getBaseName() as base_name
order by abs_path
