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
 * Потенциально опасный вызов Python: (CWE, категория, сигнатура).
 */
predicate dangerousCall(Call c, string cwe, string category, string signature) {
  // CWE-095: Динамическое выполнение кода
  c.getFunc().(Name).getId() = "eval" and
  cwe = "CWE-095" and category = "Динамическое исполнение кода" and signature = "eval"
  or
  c.getFunc().(Name).getId() = "exec" and
  cwe = "CWE-095" and category = "Динамическое исполнение кода" and signature = "exec"
  or
  c.getFunc().(Name).getId() = "compile" and
  cwe = "CWE-095" and category = "Динамическое исполнение кода" and signature = "compile"
  or
  // CWE-078: Внедрение команд ОС
  c.getFunc().(Attribute).getObject().(Name).getId() = "os" and
  c.getFunc().(Attribute).getName() = "system" and
  cwe = "CWE-078" and category = "Внедрение команд ОС" and signature = "os.system"
  or
  c.getFunc().(Attribute).getObject().(Name).getId() = "os" and
  c.getFunc().(Attribute).getName() = "popen" and
  cwe = "CWE-078" and category = "Внедрение команд ОС" and signature = "os.popen"
  or
  c.getFunc().(Attribute).getObject().(Name).getId() = "subprocess" and
  c.getFunc().(Attribute).getName() = "call" and
  cwe = "CWE-078" and category = "Внедрение команд ОС" and signature = "subprocess.call"
  or
  c.getFunc().(Attribute).getObject().(Name).getId() = "subprocess" and
  c.getFunc().(Attribute).getName() = "run" and
  cwe = "CWE-078" and category = "Внедрение команд ОС" and signature = "subprocess.run"
  or
  c.getFunc().(Attribute).getObject().(Name).getId() = "subprocess" and
  c.getFunc().(Attribute).getName() = "Popen" and
  cwe = "CWE-078" and category = "Внедрение команд ОС" and signature = "subprocess.Popen"
  or
  c.getFunc().(Attribute).getObject().(Name).getId() = "subprocess" and
  c.getFunc().(Attribute).getName() = "check_output" and
  cwe = "CWE-078" and category = "Внедрение команд ОС" and signature = "subprocess.check_output"
  or
  // CWE-502: Небезопасная десериализация
  c.getFunc().(Attribute).getObject().(Name).getId() = "pickle" and
  c.getFunc().(Attribute).getName() = "loads" and
  cwe = "CWE-502" and category = "Небезопасная десериализация" and signature = "pickle.loads"
  or
  c.getFunc().(Attribute).getObject().(Name).getId() = "pickle" and
  c.getFunc().(Attribute).getName() = "load" and
  cwe = "CWE-502" and category = "Небезопасная десериализация" and signature = "pickle.load"
  or
  c.getFunc().(Attribute).getObject().(Name).getId() = "marshal" and
  c.getFunc().(Attribute).getName() = "loads" and
  cwe = "CWE-502" and category = "Небезопасная десериализация" and signature = "marshal.loads"
  or
  c.getFunc().(Attribute).getObject().(Name).getId() = "yaml" and
  c.getFunc().(Attribute).getName() = "load" and
  cwe = "CWE-502" and category = "Небезопасная десериализация" and signature = "yaml.load"
  or
  // CWE-089: SQL-инъекция через форматирование строк
  c.getFunc().(Attribute).getName() = "execute" and
  exists(c.getAnArg().(BinaryExpr)) and
  cwe = "CWE-089" and category = "Форматирование SQL-запроса" and signature = "cursor.execute"
  or
  // CWE-706: Динамический импорт
  c.getFunc().(Name).getId() = "__import__" and
  cwe = "CWE-706" and category = "Динамический импорт" and signature = "__import__"
  or
  c.getFunc().(Attribute).getObject().(Name).getId() = "importlib" and
  c.getFunc().(Attribute).getName() = "import_module" and
  cwe = "CWE-706" and category = "Динамический импорт" and signature = "importlib.import_module"
  or
  // CWE-020: Непроверенный пользовательский ввод (input() без валидации)
  c.getFunc().(Name).getId() = "input" and
  cwe = "CWE-020" and category = "Непроверенный пользовательский ввод" and signature = "input"
  or
  // CWE-078: os.exec* и os.spawn* — замена процесса / запуск подпроцесса
  c.getFunc().(Attribute).getObject().(Name).getId() = "os" and
  c.getFunc().(Attribute).getName() = [
    "execl", "execle", "execlp", "execv", "execvp", "execvpe",
    "spawnl", "spawnle", "spawnlp", "spawnv", "spawnve", "spawnvp", "spawnvpe"
  ] and
  cwe = "CWE-078" and category = "Внедрение команд ОС" and
  signature = "os." + c.getFunc().(Attribute).getName()
  or
  // CWE-502: shelve.open — автоматически использует pickle под капотом
  c.getFunc().(Attribute).getObject().(Name).getId() = "shelve" and
  c.getFunc().(Attribute).getName() = "open" and
  cwe = "CWE-502" and category = "Небезопасная десериализация" and signature = "shelve.open"
  or
  // CWE-502: jsonpickle.decode — десериализация с выполнением кода
  c.getFunc().(Attribute).getObject().(Name).getId() = "jsonpickle" and
  c.getFunc().(Attribute).getName() = ["decode", "loads"] and
  cwe = "CWE-502" and category = "Небезопасная десериализация" and
  signature = "jsonpickle." + c.getFunc().(Attribute).getName()
  or
  // CWE-327: слабые алгоритмы хэширования (MD5, SHA-1)
  c.getFunc().(Attribute).getObject().(Name).getId() = "hashlib" and
  c.getFunc().(Attribute).getName() = ["md5", "sha1"] and
  cwe = "CWE-327" and category = "Слабый алгоритм хэширования" and
  signature = "hashlib." + c.getFunc().(Attribute).getName()
}

from Function enclosing, Call c, string cweCode, string catName, string sigName
where
  dangerousCall(c, cweCode, catName, sigName) and
  c.getScope() = enclosing and
  enclosing.getName() != "" and
  isProjectFile(enclosing.getLocation().getFile())
select
  cweCode as cwe,
  catName as category,
  sigName as signature,
  enclosing.getQualifiedName() as function_name,
  enclosing.getLocation().getFile().getAbsolutePath() as func_file,
  c.getLocation().getStartLine() as line
order by func_file, line
