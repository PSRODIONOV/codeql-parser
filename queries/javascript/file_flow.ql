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

string getFileAccessType(string methodName) {
  methodName = ["readFile", "readFileSync"] and result = "чтение из файла"
  or
  methodName = ["writeFile", "writeFileSync"] and result = "запись в файл"
  or
  methodName = ["appendFile", "appendFileSync"] and result = "запись в файл"
}

from Function caller, MethodCallExpr call, StringLiteral fileName, string methodName
where
  isProjectFile(caller.getFile()) and
  call.getEnclosingFunction() = caller and
  methodName = call.getMethodName() and
  exists(getFileAccessType(methodName)) and
  fileName = call.getArgument(0) and
  exists(qname(caller))
select
  qname(caller) as function_name,
  caller.getFile().getAbsolutePath() as func_file,
  fileName.getStringValue() as file_name,
  getFileAccessType(methodName) as access_type,
  call.getLocation().getStartLine() as access_line
order by file_name, function_name
