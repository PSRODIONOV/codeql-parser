/**
 * @name Источники данных информационных объектов (ИО)
 * @description Для каждого ИО (переменной/поля), в который попадают данные из
 *              внешнего источника (СУБД, файл, сеть, ввод, окружение), выводит
 *              категорию источника, его расположение и эвристический флаг
 *              возможной конфиденциальности. Прототип для C++.
 * @kind table
 * @id cps/cpp/data-sources
 */
import cpp
import semmle.code.cpp.dataflow.new.DataFlow
import semmle.code.cpp.dataflow.new.TaintTracking

/** Файл принадлежит анализируемому проекту (исходники, не артефакты сборки). */
predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}") and
  file.getExtension() = ["cpp", "c", "h", "hpp"] and
  not file.getAbsolutePath().matches("%CMakeFiles%") and
  not file.getAbsolutePath().matches("%/usr/include%") and
  not file.getAbsolutePath().matches("%/usr/lib%") and
  not file.getAbsolutePath().matches("%/lib/%") and
  not file.getAbsolutePath().matches("%/build/%") and
  not file.getAbsolutePath().matches("%\\build\\%")
}

/** Имя ИО — как в info_objects.ql / data_matrix.ql (для совпадения нумерации). */
string varName(Variable v) {
  exists(v.getQualifiedName()) and result = v.getQualifiedName()
  or
  not exists(v.getQualifiedName()) and
  result = v.(LocalScopeVariable).getFunction().getQualifiedName() + "::" + v.getName()
}

/** Вид ИО — как в info_objects.ql. */
string getVariableKind(Variable v) {
  v instanceof Parameter and result = "parameter"
  or
  v instanceof LocalScopeVariable and not v instanceof Parameter and result = "local variable"
  or
  v instanceof GlobalVariable and v.isStatic() and result = "static global variable"
  or
  v instanceof GlobalVariable and not v.isStatic() and result = "global variable"
  or
  v instanceof MemberVariable and v.isStatic() and result = "static field"
  or
  v instanceof MemberVariable and not v.isStatic() and result = "field"
  or
  not v instanceof Parameter and not v instanceof LocalScopeVariable and
  not v instanceof GlobalVariable and not v instanceof MemberVariable and result = "variable"
}

/**
 * Источники, ВОЗВРАЩАЮЩИЕ данные значением вызова (return value):
 *   функция с именем `name` → категория `cat`.
 */
predicate returnSourceCat(string name, string cat) {
  name = "getenv" and cat = "Окружение"
  or
  name = ["PQgetvalue", "PQgetCopyData",
          "sqlite3_column_text", "sqlite3_column_blob",
          "mysql_fetch_row", "SQLGetData"] and cat = "СУБД"
  or
  name = ["fgets", "fgetc", "getc"] and cat = "Файл"
}

/**
 * Источники, ЗАПОЛНЯЮЩИЕ буфер-аргумент (output parameter):
 *   функция `name`, индекс аргумента-буфера `argIdx` → категория `cat`.
 */
predicate bufferSourceCat(string name, int argIdx, string cat) {
  name = "fread" and argIdx = 0 and cat = "Файл"
  or
  name = "read" and argIdx = 1 and cat = "Файл"
  or
  name = ["recv", "recvfrom"] and argIdx = 1 and cat = "Сеть"
  or
  name = "fscanf" and argIdx = [2 .. 9] and cat = "Файл"
  or
  name = "scanf" and argIdx = [1 .. 9] and cat = "Ввод"
}

/** ИО `v` получает значение `value` (инициализатор или присваивание). */
predicate storeIntoVar(DataFlow::Node value, Variable v) {
  isProjectFile(v.getFile()) and
  (
    v.getInitializer().getExpr() = value.asExpr()
    or
    exists(AssignExpr a | a.getRValue() = value.asExpr() and a.getLValue() = v.getAnAccess())
  )
}

/** Taint от возвращаемого значения источника к месту записи в ИО. */
module SrcCfg implements DataFlow::ConfigSig {
  predicate isSource(DataFlow::Node n) {
    exists(FunctionCall fc | fc = n.asExpr() and returnSourceCat(fc.getTarget().getName(), _))
  }

  predicate isSink(DataFlow::Node n) { exists(Variable v | storeIntoVar(n, v)) }
}

module SrcFlow = TaintTracking::Global<SrcCfg>;

/** Эвристика «имя похоже на конфиденциальные данные». */
predicate looksConfidential(Variable v) {
  v.getName()
      .toLowerCase()
      .matches(["%pass%", "%pwd%", "%secret%", "%token%", "%key%", "%cred%", "%ssn%",
                "%passport%", "%inn%", "%email%", "%phone%", "%card%", "%fio%", "%birth%"])
}

/** Флаг конфиденциальности «да»/«нет» для колонки отчёта. */
string confidentialFlag(Variable v) {
  if looksConfidential(v) then result = "да" else result = "нет"
}

/** Единая связь «ИО ← источник данных категории». */
predicate ioDataSource(Variable v, string category, string srcFile, int srcLine) {
  // 1. Поток от возвращаемого значения источника к записи в ИО.
  exists(DataFlow::Node src, DataFlow::Node snk, FunctionCall fc |
    src.asExpr() = fc and
    returnSourceCat(fc.getTarget().getName(), category) and
    SrcFlow::flow(src, snk) and
    storeIntoVar(snk, v) and
    srcFile = fc.getFile().getAbsolutePath() and
    srcLine = fc.getLocation().getStartLine()
  )
  or
  // 2. ИО используется как буфер-приёмник output-аргумента источника.
  exists(FunctionCall fc, int i |
    bufferSourceCat(fc.getTarget().getName(), i, category) and
    fc.getArgument(i) = v.getAnAccess() and
    isProjectFile(v.getFile()) and
    srcFile = fc.getFile().getAbsolutePath() and
    srcLine = fc.getLocation().getStartLine()
  )
}

from Variable v, string category, string srcFile, int srcLine
where ioDataSource(v, category, srcFile, srcLine)
select
  varName(v) as variable_name,
  v.getName() as name,
  getVariableKind(v) as kind,
  category as source_category,
  srcFile as source_file,
  srcLine as source_line,
  confidentialFlag(v) as confidential
order by source_category, variable_name
