import cpp

/** Файл принадлежит тестовому проекту */
predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}") and
  file.getExtension() = ["cpp", "c", "h", "hpp"] and not file.getAbsolutePath().matches("%CMakeFiles%") and not file.getAbsolutePath().matches("%/usr/include%") and not file.getAbsolutePath().matches("%/usr/lib%") and not file.getAbsolutePath().matches("%/lib/%") and not file.getAbsolutePath().matches("%.moc%") and not file.getAbsolutePath().matches("%.rcc%") and not file.getAbsolutePath().matches("%.ui%") and not file.getAbsolutePath().matches("%.._._%")
}

from FunctionCall fc, Function caller, Function callee
where
  fc.getEnclosingFunction() = caller and
  fc.getTarget() = callee and
  caller != callee and
  isProjectFile(caller.getFile()) and
  isProjectFile(callee.getFile())
select
  caller.getQualifiedName() as caller_name,
  callee.getQualifiedName() as callee_name,
  caller.getFile().getAbsolutePath() as caller_file,
  // Файл объявления callee (как `file` в functional_objects.ql): разрешает
  // неоднозначность одноимённых функций (static-тёзки, перегрузки).
  callee.getFile().getAbsolutePath() as callee_file,
  fc.getLocation().getStartLine() as call_line
order by callee_name, caller_name, call_line
