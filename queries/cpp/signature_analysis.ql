import cpp

/** Файл принадлежит тестовому проекту (исходники, не артефакты сборки) */
predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}") and
  file.getExtension() = ["cpp", "c", "h", "hpp"] and not file.getAbsolutePath().matches("%CMakeFiles%") and not file.getAbsolutePath().matches("%/usr/include%") and not file.getAbsolutePath().matches("%/usr/lib%") and not file.getAbsolutePath().matches("%/lib/%") and not file.getAbsolutePath().matches("%.moc%") and not file.getAbsolutePath().matches("%.rcc%") and not file.getAbsolutePath().matches("%.ui%") and not file.getAbsolutePath().matches("%.._._%") and
  not file.getAbsolutePath().matches("%/build/%") and
  not file.getAbsolutePath().matches("%\\build\\%")
}

/**
 * Потенциально опасная функция, выявляемая по имени.
 * Каждое имя сопоставлено ровно одной категории CWE.
 */
predicate dangerousByName(string name, string cwe, string category) {
  name =
    [
      "system", "popen", "_popen",
      "execl", "execlp", "execle", "execv", "execvp", "execvpe", "dlopen",
      "WinExec", "ShellExecuteA", "ShellExecuteW",
      "CreateProcessA", "CreateProcessW"
    ] and
  cwe = "CWE-078" and
  category = "Внедрение команд ОС"
  or
  name =
    [
      "strcpy", "strcat", "sprintf", "vsprintf", "scanf", "sscanf", "memcpy", "strncpy", "strncat"
    ] and
  cwe = "CWE-120" and
  category = "Переполнение буфера"
  or
  name = ["gets", "atoi", "atol", "atoll", "tmpnam", "mktemp", "getpass", "cuserid", "tempnam"] and
  cwe = "CWE-676" and
  category = "Опасная функция"
}

/**
 * Функции с форматной строкой и индекс аргумента-формата.
 * Опасны (CWE-134), только если формат — не строковый литерал
 * (передаётся извне: возможна атака через форматную строку).
 */
predicate formatStringFunction(string name, int fmtIndex) {
  name = "printf" and fmtIndex = 0
  or
  name = "fprintf" and fmtIndex = 1
  or
  name = "snprintf" and fmtIndex = 2
  or
  name = "vprintf" and fmtIndex = 0
  or
  name = "vfprintf" and fmtIndex = 1
  or
  name = "vsprintf" and fmtIndex = 1
  or
  name = "vsnprintf" and fmtIndex = 2
  or
  name = "wprintf" and fmtIndex = 0
  or
  name = "fwprintf" and fmtIndex = 1
  or
  name = "swprintf" and fmtIndex = 2
  or
  name = "asprintf" and fmtIndex = 1
  or
  name = "vasprintf" and fmtIndex = 1
  or
  name = "dprintf" and fmtIndex = 1
}

/** Вызов потенциально опасной конструкции: (CWE, категория, сигнатура). */
predicate dangerousCall(FunctionCall fc, string cwe, string category, string signature) {
  exists(string name |
    fc.getTarget().hasGlobalName(name) and
    dangerousByName(name, cwe, category) and
    signature = name
  )
  or
  exists(string name, int idx |
    fc.getTarget().hasGlobalName(name) and
    formatStringFunction(name, idx) and
    not fc.getArgument(idx).getFullyConverted() instanceof StringLiteral and
    cwe = "CWE-134" and
    category = "Форматная строка" and
    signature = name
  )
}

from FunctionCall fc, Function enclosing, string cweCode, string cat, string sig
where
  dangerousCall(fc, cweCode, cat, sig) and
  enclosing = fc.getEnclosingFunction() and
  isProjectFile(enclosing.getFile())
select
  cweCode as cwe,
  cat as category,
  sig as signature,
  enclosing.getQualifiedName() as function_name,
  enclosing.getFile().getAbsolutePath() as func_file,
  fc.getLocation().getStartLine() as line
order by func_file, line
