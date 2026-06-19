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
  f instanceof Destructor and result = "destructor"
  or
  f.getName() = "main" and result = "entry point"
  or
  f instanceof MemberFunction and not f instanceof Constructor and not f instanceof Destructor and result = "member function"
  or
  not f instanceof MemberFunction and not f instanceof Constructor and not f instanceof Destructor and not f.getName() = "main" and result = "function"
}

/** Файл принадлежит тестовому проекту */
predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}") and
  file.getExtension() = ["cpp", "c", "h", "hpp"] and
  not file.getAbsolutePath().matches("%CMakeFiles%") and
  not file.getAbsolutePath().matches("%/usr/include%") and
  not file.getAbsolutePath().matches("%/usr/lib%") and
  not file.getAbsolutePath().matches("%/lib/%") and
  not file.getAbsolutePath().matches("%.moc%") and
  not file.getAbsolutePath().matches("%.rcc%") and
  not file.getAbsolutePath().matches("%.ui%") and not file.getAbsolutePath().matches("%.._._%")
}

from Function f
where isProjectFile(f.getFile())
  and f.hasDefinition()
  and not f.getName().indexOf("operator") = 0
  // Функции, ЦЕЛИКОМ синтезированные макросом (напр. G_DEFINE_TYPE в GLib/GObject:
  // get_type/class_intern_init/get_instance_private) — у них нет отдельного места
  // в исходном файле (все делят одну строку вызова макроса), поэтому их нельзя
  // ни показать как отдельный ФО, ни инструментировать для динамики (см. probe_points.ql).
  and not f.isInMacroExpansion()
  // Неявные (implicit) конструкторы/деструкторы — компилятор сам генерирует их
  // для класса/шаблона без явного кода программиста; реального места в файле
  // тоже нет (CodeQL репортит позицию как имя класса).
  and not f.isCompilerGenerated()
select
  f.getQualifiedName() as qualified_name,
  f.getName() as name,
  getParentTypeName(f) as parent_type,
  f.getFile().getAbsolutePath() as file,
  f.getLocation().getStartLine() as line,
  getFunctionKind(f) as kind
order by file, line, qualified_name