import javascript

predicate isProjectFile(File file) {
  file.getAbsolutePath().matches("${PROJECT_PATTERN}") and
  not file.getAbsolutePath().matches("%test-project-js-db%") and
  not file.getAbsolutePath().matches("%node_modules%")
}

/** РџРѕР»РЅРѕРµ РёРјСЏ С„СѓРЅРєС†РёРё: ClassName.method РёР»Рё РїСЂРѕСЃС‚Рѕ name. */
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

/** РРјСЏ РєР»Р°СЃСЃР° (РµСЃР»Рё РјРµС‚РѕРґ), РёРЅР°С‡Рµ РїСѓСЃС‚Рѕ. */
string getParentType(Function f) {
  exists(MethodDefinition md | md.getBody() = f | result = md.getDeclaringClass().getName())
  or
  not exists(MethodDefinition md | md.getBody() = f) and result = ""
}

/** Р’РёРґ С„СѓРЅРєС†РёРѕРЅР°Р»СЊРЅРѕРіРѕ РѕР±СЉРµРєС‚Р°. */
string getKind(Function f) {
  exists(MethodDefinition md | md.getBody() = f and md.getName() = "constructor" |
    result = "constructor"
  )
  or
  exists(MethodDefinition md | md.getBody() = f and md.getName() != "constructor" |
    result = "member function"
  )
  or
  not exists(MethodDefinition md | md.getBody() = f) and
  f.getName() = "main" and
  result = "entry point"
  or
  not exists(MethodDefinition md | md.getBody() = f) and
  f.getName() != "" and
  f.getName() != "main" and
  result = "function"
}

from Function f
where
  isProjectFile(f.getFile()) and
  exists(f.getBody()) and
  exists(qname(f)) and
  exists(getKind(f))
select
  qname(f) as qualified_name,
  f.getName() as name,
  getParentType(f) as parent_type,
  f.getFile().getAbsolutePath() as file,
  f.getLocation().getStartLine() as line,
  getKind(f) as kind
order by file, line, qualified_name
