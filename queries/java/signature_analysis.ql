import java

predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}")
}

string qname(Callable c) {
  result = c.getDeclaringType().getQualifiedName() + "." + c.getName()
}

/**
 * Потенциально опасный вызов метода: (CWE, категория, сигнатура).
 * Детект по имени метода и объявляющему типу.
 */
predicate dangerousCall(MethodCall mc, string cwe, string category, string signature) {
  // CWE-078: запуск команд ОС.
  // Сопоставление по простому имени типа: при сборке БД без полного rt.jar
  // getQualifiedName() возвращает короткое имя ("Runtime"), поэтому
  // используем getName() объявляющего типа.
  mc.getMethod().getName() = "exec" and
  mc.getMethod().getDeclaringType().getName() = "Runtime" and
  cwe = "CWE-078" and
  category = "Внедрение команд ОС" and
  signature = "Runtime.exec"
  or
  mc.getMethod().getName() = "start" and
  mc.getMethod().getDeclaringType().getName() = "ProcessBuilder" and
  cwe = "CWE-078" and
  category = "Внедрение команд ОС" and
  signature = "ProcessBuilder.start"
  or
  // CWE-095: динамическое исполнение
  mc.getMethod().getName() = ["eval", "exec"] and
  mc.getMethod().getDeclaringType().getName().matches("%ScriptEngine%") and
  cwe = "CWE-095" and
  category = "Динамическое исполнение кода" and
  signature = "ScriptEngine.eval"
  or
  // CWE-094: выполнение кода через Groovy
  mc.getMethod().getName() = ["evaluate", "run"] and
  mc.getMethod().getDeclaringType().getName() = "GroovyShell" and
  cwe = "CWE-094" and
  category = "Выполнение кода (Groovy)" and
  signature = "GroovyShell." + mc.getMethod().getName()
  or
  // CWE-089: SQL — jdbc Statement.*
  mc.getMethod().getName() = ["execute", "executeQuery", "executeUpdate", "executeBatch", "executeLargeUpdate"] and
  mc.getMethod().getDeclaringType().getName().matches("%Statement%") and
  cwe = "CWE-089" and
  category = "SQL-запрос" and
  signature = "Statement." + mc.getMethod().getName()
  or
  // CWE-089: SQL — JPA EntityManager
  mc.getMethod().getName() = ["createQuery", "createNativeQuery"] and
  mc.getMethod().getDeclaringType().getName().matches("%EntityManager%") and
  cwe = "CWE-089" and
  category = "SQL-запрос (JPA)" and
  signature = "EntityManager." + mc.getMethod().getName()
  or
  // CWE-502: небезопасная десериализация — ObjectInputStream
  mc.getMethod().getName() = ["readObject", "readUnshared"] and
  mc.getMethod().getDeclaringType().getName() = "ObjectInputStream" and
  cwe = "CWE-502" and
  category = "Небезопасная десериализация" and
  signature = "ObjectInputStream." + mc.getMethod().getName()
  or
  // CWE-611: XXE через XMLDecoder (десериализация XML в объекты)
  mc.getMethod().getName() = "readObject" and
  mc.getMethod().getDeclaringType().getName() = "XMLDecoder" and
  cwe = "CWE-611" and
  category = "XML-инъекция (XBE/XXE)" and
  signature = "XMLDecoder.readObject"
  or
  // CWE-090: LDAP-инъекция
  mc.getMethod().getName() = "search" and
  mc.getMethod().getDeclaringType().getName().matches("%DirContext%") and
  cwe = "CWE-090" and
  category = "LDAP-инъекция" and
  signature = "DirContext.search"
  or
  // CWE-330: небезопасный ГСЧ (Math.random вместо SecureRandom)
  mc.getMethod().getName() = "random" and
  mc.getMethod().getDeclaringType().getName() = "Math" and
  cwe = "CWE-330" and
  category = "Небезопасный ГСЧ" and
  signature = "Math.random"
}

from MethodCall mc, Callable enclosing, string cweCode, string cat, string sig
where
  dangerousCall(mc, cweCode, cat, sig) and
  enclosing = mc.getEnclosingCallable() and
  isProjectFile(enclosing.getFile())
select
  cweCode as cwe,
  cat as category,
  sig as signature,
  qname(enclosing) as function_name,
  enclosing.getFile().getAbsolutePath() as func_file,
  mc.getLocation().getStartLine() as line
order by func_file, line
