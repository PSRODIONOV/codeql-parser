import cpp

/** Файл принадлежит тестовому проекту (исходники, не артефакты сборки) */
predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}") and
  file.getExtension() = ["cpp", "c", "h", "hpp"] and not file.getAbsolutePath().matches("%CMakeFiles%") and not file.getAbsolutePath().matches("%/usr/include%") and not file.getAbsolutePath().matches("%/usr/lib%") and not file.getAbsolutePath().matches("%/lib/%") and not file.getAbsolutePath().matches("%.moc%") and not file.getAbsolutePath().matches("%.rcc%") and not file.getAbsolutePath().matches("%.ui%") and not file.getAbsolutePath().matches("%.._._%") and
  not file.getAbsolutePath().matches("%/build/%") and
  not file.getAbsolutePath().matches("%\\build\\%")
}

/** Переменная — файловый поток (ifstream / ofstream / fstream). */
predicate isFileStream(Variable v) {
  v.getType().getName().matches("%fstream%")
}

/**
 * Тип файлового доступа по типу потока:
 *   "чтение из файла" — ifstream;
 *   "запись в файл"   — ofstream;
 *   "файловый ввод-вывод" — fstream (двунаправленный).
 */
string getFileAccessType(Variable v) {
  v.getType().getName().matches("%ifstream%") and result = "чтение из файла"
  or
  v.getType().getName().matches("%ofstream%") and result = "запись в файл"
  or
  v.getType().getName().matches("%fstream%") and
  not v.getType().getName().matches("%ifstream%") and
  not v.getType().getName().matches("%ofstream%") and
  result = "файловый ввод-вывод"
}

/**
 * Файловые потоки и имена файлов, с которыми они связаны.
 * Имя файла берётся из строкового литерала на той же строке, что и объявление
 * потока (идиома `std::ofstream ofs("file.dat")`): строковый литерал обёрнут в
 * неявные приведения и не является прямым потомком ConstructorCall, поэтому
 * сопоставляем по (функция, строка объявления).
 */
from Function f, LocalScopeVariable v, StringLiteral sl
where
  isProjectFile(f.getFile()) and
  v.getFunction() = f and
  isFileStream(v) and
  sl.getEnclosingFunction() = f and
  sl.getLocation().getStartLine() = v.getLocation().getStartLine()
select
  f.getQualifiedName() as function_name,
  f.getFile().getAbsolutePath() as func_file,
  sl.getValue() as file_name,
  getFileAccessType(v) as access_type,
  v.getLocation().getStartLine() as access_line
order by file_name, function_name
