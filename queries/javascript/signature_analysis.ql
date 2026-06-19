import javascript

predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}") and
  not file.getAbsolutePath().matches("%test-project-js-db%") and
  not file.getAbsolutePath().matches("%node_modules%")
}

string qname(Function f) {
  exists(MethodDefinition md | md.getBody() = f and md.getName() != "constructor" |
    result = md.getDeclaringClass().getName() + "." + md.getName()
  )
  or
  exists(MethodDefinition md | md.getBody() = f and md.getName() = "constructor" |
    result = md.getDeclaringClass().getName() + ".constructor"
  )
  or
  not exists(MethodDefinition md | md.getBody() = f) and
  f.getName() != "" and
  result = f.getName()
}

predicate dangerousCall(InvokeExpr call, string cwe, string category, string signature) {
  // CWE-095: eval()
  call.(CallExpr).getCallee().(VarAccess).getName() = "eval" and
  cwe = "CWE-095" and
  category = "Динамическое исполнение кода" and
  signature = "eval"
  or
  // CWE-095: new Function(...)
  call instanceof NewExpr and
  call.getCallee().(VarAccess).getName() = "Function" and
  cwe = "CWE-095" and
  category = "Динамическое исполнение кода" and
  signature = "new Function"
  or
  // CWE-095: execScript / setTimeout(string) / setInterval(string)
  call.(CallExpr).getCallee().(VarAccess).getName() = ["execScript", "executeJavaScript"] and
  cwe = "CWE-095" and
  category = "Динамическое исполнение кода" and
  signature = call.(CallExpr).getCallee().(VarAccess).getName()
  or
  // CWE-095: vm.runInNewContext / vm.runInThisContext / vm.runInContext
  call.(MethodCallExpr).getReceiver().(VarAccess).getName() = "vm" and
  call.(MethodCallExpr).getMethodName() = ["runInNewContext", "runInThisContext", "runInContext"] and
  cwe = "CWE-095" and
  category = "Динамическое исполнение кода (Node.js vm)" and
  signature = "vm." + call.(MethodCallExpr).getMethodName()
  or
  // CWE-078: child_process.exec()
  call.(MethodCallExpr).getMethodName() = "exec" and
  not call.(MethodCallExpr).getReceiver().(VarAccess).getName() = "fs" and
  cwe = "CWE-078" and
  category = "Внедрение команд ОС" and
  signature = "exec"
  or
  // CWE-078: child_process.spawn()
  call.(MethodCallExpr).getMethodName() = "spawn" and
  cwe = "CWE-078" and
  category = "Внедрение команд ОС" and
  signature = "spawn"
  or
  // CWE-078: child_process.execSync / execFile / execFileSync / spawnSync / fork
  call.(MethodCallExpr).getMethodName() = ["execSync", "execFile", "execFileSync", "spawnSync", "fork"] and
  cwe = "CWE-078" and
  category = "Внедрение команд ОС" and
  signature = call.(MethodCallExpr).getMethodName()
  or
  // CWE-089: SQL через драйверы БД (mysql, pg, sqlite3 и др.)
  call.(MethodCallExpr).getMethodName() = "query" and
  cwe = "CWE-089" and
  category = "SQL-запрос" and
  signature = "db.query"
  or
  // CWE-502: небезопасная десериализация
  call.(MethodCallExpr).getMethodName() = ["unserialize", "deserialize"] and
  cwe = "CWE-502" and
  category = "Небезопасная десериализация" and
  signature = call.(MethodCallExpr).getMethodName()
}

from Function caller, InvokeExpr call, string cw, string cat, string sig
where
  dangerousCall(call, cw, cat, sig) and
  call.getEnclosingFunction() = caller and
  isProjectFile(caller.getFile()) and
  exists(qname(caller))
select
  cw as cwe,
  cat as category,
  sig as signature,
  qname(caller) as function_name,
  caller.getFile().getAbsolutePath() as func_file,
  call.getLocation().getStartLine() as line
order by func_file, line
