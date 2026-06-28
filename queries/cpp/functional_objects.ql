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

/**
 * Геометрия вставки датчика входа/выхода тела функции.
 *
 * constexpr-функции остаются в Перечень_ФО, но не получают геометрию:
 * __TRACE_FN() вызывает обычную (не constexpr) __trace_enter(), и вставка
 * в constexpr-функцию даёт "call to non-constexpr function" и каскад
 * ошибок по зависимым шаблонам.
 */
int insLine(Function f) {
  exists(f.getBlock()) and not f.isConstexpr() and result = f.getBlock().getLocation().getStartLine()
  or
  (not exists(f.getBlock()) or f.isConstexpr()) and result = 0
}

int insCol(Function f) {
  exists(f.getBlock()) and not f.isConstexpr() and result = f.getBlock().getLocation().getStartColumn()
  or
  (not exists(f.getBlock()) or f.isConstexpr()) and result = 0
}

int endLine(Function f) {
  exists(f.getBlock()) and not f.isConstexpr() and result = f.getBlock().getLocation().getEndLine()
  or
  (not exists(f.getBlock()) or f.isConstexpr()) and result = 0
}

int endCol(Function f) {
  exists(f.getBlock()) and not f.isConstexpr() and result = f.getBlock().getLocation().getEndColumn()
  or
  (not exists(f.getBlock()) or f.isConstexpr()) and result = 0
}

from Function f
where isProjectFile(f.getFile())
  and f.hasDefinition()
  and not f.getName().indexOf("operator") = 0
  // Функции, целиком синтезированные макросом (напр. G_DEFINE_TYPE в GLib/GObject) —
  // нет отдельного места в исходнике (все делят строку вызова макроса).
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
  getFunctionKind(f) as kind,
  insLine(f) as ins_line, insCol(f) as ins_col,
  endLine(f) as end_line, endCol(f) as end_col
order by file, line, qualified_name