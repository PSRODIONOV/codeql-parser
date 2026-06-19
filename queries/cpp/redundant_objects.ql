import cpp

/** Возвращает имя родительского типа или "(global)" для свободных функций */
string getParentTypeName(Function f) {
  result = f.getDeclaringType().getName()
  or
  not exists(f.getDeclaringType()) and result = "(global)"
}

/** Определяем тип функции как строку */
string getFunctionKind(Function f) {
  f instanceof Constructor and result = "constructor"
  or
  f instanceof MemberFunction and not f instanceof Constructor and result = "member function"
  or
  not f instanceof MemberFunction and not f instanceof Constructor and result = "function"
}

/** Файл принадлежит тестовому проекту */
predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}") and
  file.getExtension() = ["cpp", "c", "h", "hpp"] and not file.getAbsolutePath().matches("%CMakeFiles%") and not file.getAbsolutePath().matches("%/usr/include%") and not file.getAbsolutePath().matches("%/usr/lib%") and not file.getAbsolutePath().matches("%/lib/%") and not file.getAbsolutePath().matches("%.moc%") and not file.getAbsolutePath().matches("%.rcc%") and not file.getAbsolutePath().matches("%.ui%") and not file.getAbsolutePath().matches("%.._._%")
}

from Function f
where
  not exists(FunctionCall fc | fc.getTarget() = f)
  and not f instanceof Destructor
  and not f.getName() = "main"
  and not f.getName().indexOf("operator") = 0
  and not f.hasDefinition()
  and isProjectFile(f.getFile())
select
  f.getQualifiedName() as qualified_name,
  f.getName() as name,
  f.getFile().getBaseName() as file,
  f.getLocation().getStartLine() as line
