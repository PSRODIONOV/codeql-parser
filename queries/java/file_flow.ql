import java

predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}")
}

/** Полное имя ФО: <Тип>.<метод> (как в functional_objects.ql). */
string qname(Callable c) {
  result = c.getDeclaringType().getQualifiedName() + "." + c.getName()
}

/** Тип файлового доступа по имени класса потока. */
string getFileAccessType(string typeName) {
  typeName = "FileReader" and result = "чтение из файла"
  or
  typeName = "FileWriter" and result = "запись в файл"
}

/**
 * Файловые потоки и имена файлов. Имя файла — строковый литерал-аргумент
 * конструктора FileReader/FileWriter (идиома `new FileReader("file.dat")`).
 */
from Callable caller, ClassInstanceExpr cie, string typeName, StringLiteral fileName
where
  isProjectFile(caller.getFile()) and
  cie.getEnclosingCallable() = caller and
  typeName = cie.getConstructedType().getName() and
  (typeName = "FileReader" or typeName = "FileWriter") and
  fileName = cie.getAnArgument()
select
  qname(caller) as function_name,
  caller.getFile().getAbsolutePath() as func_file,
  fileName.getValue() as file_name,
  getFileAccessType(typeName) as access_type,
  cie.getLocation().getStartLine() as access_line
order by file_name, function_name
