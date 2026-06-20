// queries/php/all_queries.sc
// Joern v4 script: PHP source analysis — extracts all 9 analysis datasets.
//
// Invoked by joern_analyzer.py:
//   joern --workspace <dir> --script all_queries.sc \
//         --params src=<b64>,out=<b64>,pat=<b64>
//
// Parameters (URL-safe base64, no padding):
//   src — PHP source directory (absolute path)
//   out — output file path for JSONL results
//   pat — substring pattern for file filtering (empty = all files)
//
// Output format: one JSON object per line.  Every object carries a "_ds"
// field identifying the dataset ("functional", "info", ...).  The column
// names match the RAW_SCHEMA in project_db.py exactly.

import io.shiftleft.codepropertygraph.generated.nodes._
import io.shiftleft.semanticcpg.language._
import scala.collection.mutable
import java.io.{BufferedWriter, FileWriter}

// Parameters are injected by joern_analyzer.py into a temp copy of this script:
//   val _inp = "<url-safe-base64 of source path>"
//   val _out = "<url-safe-base64 of output jsonl path>"
//   val _pat = "<url-safe-base64 of filter pattern>"
// __PARAMS__

@main def main(): Unit = {

  // ── Decode URL-safe base64 parameters ──────────────────────────────────────
  def b64dec(s: String): String = {
    val padded = s + "=" * ((4 - s.length % 4) % 4)
    new String(java.util.Base64.getUrlDecoder.decode(padded), "UTF-8")
  }
  val inputPath  = b64dec(_inp)
  val outputPath = b64dec(_out)
  val pattern    = b64dec(_pat)

  // ── JSON helpers ──────────────────────────────────────────────────────────
  def jstr(s: String): String = {
    val sb = new java.lang.StringBuilder
    sb.append('"')
    s.foreach {
      case '"'  => sb.append("\\\"")
      case '\\' => sb.append("\\\\")
      case '\n' => sb.append("\\n")
      case '\r' => sb.append("\\r")
      case '\t' => sb.append("\\t")
      case c if c < 0x20 => sb.append(f"\\u${c.toInt}%04x")
      case c    => sb.append(c)
    }
    sb.append('"')
    sb.toString
  }

  // Emit one JSONL line with dataset tag + variable number of key-value pairs
  def jrow(ds: String, kvs: (String, String)*): String = {
    val pairs = ("_ds" -> ds) +: kvs
    "{" + pairs.map { case (k, v) => s"${jstr(k)}:${jstr(v)}" }.mkString(",") + "}"
  }

  // ── File path pattern filter ──────────────────────────────────────────────
  def matches(path: String): Boolean =
    pattern.isEmpty || path.contains(pattern)

  // ── lineNumberEnd helper ──────────────────────────────────────────────────
  // Joern 4.x removed lineNumberEnd from most node types.
  // Approximate it as the maximum lineNumber in the AST subtree.
  def lineEnd(n: AstNode, default: Int): Int =
    n.ast.flatMap(_.lineNumber).maxOption.getOrElse(default)

  // ── Import PHP source into CPG ────────────────────────────────────────────
  try {
    importCode.php(inputPath)
  } catch {
    case _: Exception => importCode(inputPath, language = "PHP")
  }

  // ── Output writer ─────────────────────────────────────────────────────────
  val bw = new BufferedWriter(new FileWriter(outputPath, false))
  def emit(line: String): Unit = { bw.write(line); bw.newLine() }

  try {

    // ── isInCatch: true if node is inside a catch-clause block ──────────────
    // In Joern 4.x, `astIn` was renamed; use `_astIn` with AstNode cast.
    def isInCatch(node: AstNode): Boolean = {
      var current: Option[AstNode] = node._astIn.collectFirst { case n: AstNode => n }
      var found = false
      var stop  = false
      while (current.isDefined && !stop) {
        current.get match {
          case cs: ControlStructure if cs.controlStructureType == "CATCH" =>
            found = true; stop = true
          case _: Method =>
            stop = true
          case n: AstNode =>
            current = n._astIn.collectFirst { case p: AstNode => p }
        }
      }
      found
    }

    // ────────────────────────────────────────────────────────────────────────
    // 1. functional_objects: functions, methods, constructors
    // ────────────────────────────────────────────────────────────────────────
    cpg.method
      .filterNot(_.isExternal)
      .filter(m => matches(m.filename))
      .filterNot(m => m.name.startsWith("<") || m.name.isEmpty)
      .foreach { m =>
        val parentType = m.typeDecl.fullName.headOption.getOrElse("")
        // In Joern 4.x, isConstructor is a traversal step (Iterator[Method]), not Boolean
        val kind =
          if (m.isConstructor.nonEmpty)                           "constructor"
          else if (parentType.nonEmpty && parentType != "<global>") "method"
          else                                                     "function"
        emit(jrow("functional",
          "qualified_name" -> m.fullName,
          "name"           -> m.name,
          "parent_type"    -> parentType,
          "file"           -> m.filename,
          "line"           -> m.lineNumber.getOrElse(0).toString,
          "kind"           -> kind))
      }

    // ── class_info: class hierarchy — consumed by joern_analyzer.py for call
    // resolution; not stored in the project DB (removed after post-processing).
    cpg.typeDecl
      .filterNot(_.isExternal)
      .filter(td => matches(td.filename))
      .filterNot(td => td.name.startsWith("<") || td.name.isEmpty)
      .foreach { td =>
        td.inheritsFromTypeFullName
          .filterNot(p => p.isEmpty || p.startsWith("<"))
          .foreach { parent =>
            emit(jrow("class_info",
              "class_name"  -> td.fullName,
              "parent_name" -> parent))
          }
      }

    // ────────────────────────────────────────────────────────────────────────
    // 2. info_objects: local variables and parameters
    // ────────────────────────────────────────────────────────────────────────
    cpg.method
      .filterNot(_.isExternal)
      .filter(m => matches(m.filename))
      .filterNot(m => m.name.startsWith("<") || m.name.isEmpty)
      .foreach { m =>
        m.local.foreach { v =>
          emit(jrow("info",
            "qualified_name" -> (m.fullName + "." + v.name),
            "name"           -> v.name,
            "type_name"      -> v.typeFullName,
            "file"           -> m.filename,
            "line"           -> v.lineNumber.getOrElse(m.lineNumber.getOrElse(0)).toString,
            "kind"           -> "local variable"))
        }
        m.parameter
          .filterNot(p => p.name == "this" || p.name == "self")
          .foreach { p =>
            emit(jrow("info",
              "qualified_name" -> (m.fullName + "." + p.name),
              "name"           -> p.name,
              "type_name"      -> p.typeFullName,
              "file"           -> m.filename,
              "line"           -> p.lineNumber.getOrElse(m.lineNumber.getOrElse(0)).toString,
              "kind"           -> "parameter"))
          }
      }

    // ────────────────────────────────────────────────────────────────────────
    // 3. files: PHP files included in the CPG
    // ────────────────────────────────────────────────────────────────────────
    cpg.file
      .filterNot(f => f.name == "<unknown>" || f.name.isEmpty)
      .filter(f => matches(f.name))
      .foreach { f =>
        val base = f.name.split("[/\\\\]").lastOption.getOrElse(f.name)
        emit(jrow("files", "abs_path" -> f.name, "base_name" -> base))
      }

    // ────────────────────────────────────────────────────────────────────────
    // 4. control_matrix: function-call relationships
    // In Joern 4.x, .method on a Call returns a single Method (not Iterator),
    // so .filename and .fullName are plain Strings — no headOption needed.
    // ────────────────────────────────────────────────────────────────────────
    // Joern internal names that are not real PHP calls: string interpolation
    // ("encaps"), array construction ("array"), and foreach lowering ("Iterator.*").
    val _callArtifacts = Set("encaps", "array")
    cpg.call
      .filterNot(_.name.startsWith("<operator>"))
      .filter(c => matches(c.method.filename))
      .foreach { c =>
        val callerName = c.method.fullName
        val callerFile = c.method.filename
        val calleeOpt  = c.callee.headOption
        val calleeName = calleeOpt.map(_.fullName).getOrElse(c.name)
        if (!_callArtifacts(c.name) && !calleeName.startsWith("Iterator.")) {
          val calleeFile = calleeOpt.map(_.filename).getOrElse("")
          emit(jrow("control",
            "caller_name" -> callerName,
            "callee_name" -> calleeName,
            "caller_file" -> callerFile,
            "callee_file" -> calleeFile,
            "call_line"   -> c.lineNumber.getOrElse(0).toString))
        }
      }

    // ────────────────────────────────────────────────────────────────────────
    // 5. data_matrix: variable read/write accesses
    // ────────────────────────────────────────────────────────────────────────
    cpg.identifier
      .filterNot(id => id.name.isEmpty || id.name == "this" || id.name == "self")
      .filter(id => matches(id.method.filename))
      .foreach { id =>
        val funcName = id.method.fullName
        val funcFile = id.method.filename
        val isWrite = id.astParent.collect { case c: Call => c }.exists { c =>
          c.name.startsWith("<operator>.assignment") &&
            c.argument.order(1).headOption.exists(_.id == id.id)
        }
        emit(jrow("data",
          "function_name" -> funcName,
          "variable_name" -> id.name,
          "func_file"     -> funcFile,
          "access_line"   -> id.lineNumber.getOrElse(0).toString,
          "access_type"   -> (if (isWrite) "write" else "read")))
      }

    // ────────────────────────────────────────────────────────────────────────
    // 6. arg_flow: call-site argument → callee parameter mapping
    // ────────────────────────────────────────────────────────────────────────
    cpg.call
      .filterNot(_.name.startsWith("<operator>"))
      .filter(c => matches(c.method.filename))
      .foreach { c =>
        val callerName = c.method.fullName
        val callerFile = c.method.filename
        val calleeName = c.callee.fullName.headOption.getOrElse(c.name)
        if (!_callArtifacts(c.name) && !calleeName.startsWith("Iterator.")) {
          c.argument.foreach { arg =>
            val callerVar = arg match {
              case id: Identifier => id.name
              case _              => arg.code.take(80)
            }
            val paramVar = c.callee.parameter
              .order(arg.argumentIndex)
              .name.headOption
              .getOrElse(arg.argumentIndex.toString)
            emit(jrow("arg_flow",
              "caller_name" -> callerName,
              "callee_name" -> calleeName,
              "caller_var"  -> callerVar,
              "param_var"   -> paramVar,
              "caller_file" -> callerFile,
              "call_line"   -> c.lineNumber.getOrElse(0).toString))
          }
        }
      }

    // ────────────────────────────────────────────────────────────────────────
    // 7. file_flow: calls to PHP file I/O functions
    // ────────────────────────────────────────────────────────────────────────
    val phpFileOps: Map[String, String] = Map(
      "fopen"              -> "open",
      "fclose"             -> "close",
      "fread"              -> "read",
      "fwrite"             -> "write",
      "fgets"              -> "read",
      "fputs"              -> "write",
      "fputsv"             -> "write",
      "file_get_contents"  -> "read",
      "file_put_contents"  -> "write",
      "file_exists"        -> "access",
      "file"               -> "read",
      "unlink"             -> "delete",
      "rename"             -> "write",
      "copy"               -> "write",
      "mkdir"              -> "write",
      "rmdir"              -> "delete",
      "opendir"            -> "open",
      "readdir"            -> "read",
      "closedir"           -> "close",
      "scandir"            -> "read",
      "glob"               -> "read",
      "move_uploaded_file" -> "write",
      "readfile"           -> "read",
      "realpath"           -> "access",
      "is_file"            -> "access",
      "is_dir"             -> "access",
      "tempnam"            -> "write",
      "tmpfile"            -> "write")

    cpg.call
      .filter(c => phpFileOps.contains(c.name.toLowerCase))
      .filter(c => matches(c.method.filename))
      .foreach { c =>
        val funcName   = c.method.fullName
        val funcFile   = c.method.filename
        val fileArg    = c.argument.order(1).code.headOption.getOrElse("")
        val accessType = phpFileOps.getOrElse(c.name.toLowerCase, "access")
        emit(jrow("file_flow",
          "function_name" -> funcName,
          "func_file"     -> funcFile,
          "file_name"     -> fileArg,
          "access_type"   -> accessType,
          "access_line"   -> c.lineNumber.getOrElse(0).toString))
      }

    // ────────────────────────────────────────────────────────────────────────
    // 8. signature_analysis: dangerous PHP patterns mapped to CWEs
    // ────────────────────────────────────────────────────────────────────────
    case class Sig(cwe: String, cat: String, sig: String)
    val phpSigs: Map[String, Sig] = Map(
      "eval"              -> Sig("CWE-95",  "Code Injection",    "eval()"),
      "exec"              -> Sig("CWE-78",  "OS Command Inj.",   "exec()"),
      "system"            -> Sig("CWE-78",  "OS Command Inj.",   "system()"),
      "shell_exec"        -> Sig("CWE-78",  "OS Command Inj.",   "shell_exec()"),
      "passthru"          -> Sig("CWE-78",  "OS Command Inj.",   "passthru()"),
      "popen"             -> Sig("CWE-78",  "OS Command Inj.",   "popen()"),
      "proc_open"         -> Sig("CWE-78",  "OS Command Inj.",   "proc_open()"),
      "mysql_query"       -> Sig("CWE-89",  "SQL Injection",     "mysql_query()"),
      "mysqli_query"      -> Sig("CWE-89",  "SQL Injection",     "mysqli_query()"),
      "pg_query"          -> Sig("CWE-89",  "SQL Injection",     "pg_query()"),
      "unserialize"       -> Sig("CWE-502", "Deserialization",   "unserialize()"),
      "md5"               -> Sig("CWE-916", "Weak Hash",         "md5()"),
      "sha1"              -> Sig("CWE-916", "Weak Hash",         "sha1()"),
      "base64_decode"     -> Sig("CWE-116", "Encoding",          "base64_decode()"),
      "assert"            -> Sig("CWE-95",  "Code Injection",    "assert()"),
      "include"           -> Sig("CWE-98",  "File Inclusion",    "include"),
      "include_once"      -> Sig("CWE-98",  "File Inclusion",    "include_once"),
      "require"           -> Sig("CWE-98",  "File Inclusion",    "require"),
      "require_once"      -> Sig("CWE-98",  "File Inclusion",    "require_once"),
      "header"            -> Sig("CWE-113", "Header Injection",  "header()"),
      "setcookie"         -> Sig("CWE-614", "Sensitive Cookie",  "setcookie()"),
      "phpinfo"           -> Sig("CWE-200", "Info Exposure",     "phpinfo()"),
      "var_dump"          -> Sig("CWE-200", "Info Exposure",     "var_dump()"),
      "print_r"           -> Sig("CWE-200", "Info Exposure",     "print_r()"))

    cpg.call
      .filter(c => phpSigs.contains(c.name.toLowerCase))
      .filter(c => matches(c.method.filename))
      .foreach { c =>
        val s        = phpSigs(c.name.toLowerCase)
        val funcName = c.method.fullName
        val funcFile = c.method.filename
        emit(jrow("signature",
          "cwe"           -> s.cwe,
          "category"      -> s.cat,
          "signature"     -> s.sig,
          "function_name" -> funcName,
          "func_file"     -> funcFile,
          "line"          -> c.lineNumber.getOrElse(0).toString))
      }

    // ────────────────────────────────────────────────────────────────────────
    // 9. function_flow: control structures per function
    //
    // lineNumberEnd was removed from Joern 4.x CPG schema for most node types.
    // lineEnd() approximates it as the max lineNumber in the AST subtree.
    // ────────────────────────────────────────────────────────────────────────
    cpg.method
      .filterNot(_.isExternal)
      .filter(m => matches(m.filename))
      .filterNot(m => m.name.startsWith("<") || m.name.isEmpty)
      .foreach { m =>
        val funcName = m.fullName
        val funcFile = m.filename
        val basename = funcFile.split("[/\\\\]").lastOption.getOrElse(funcFile)

        def addFlow(
            lineStart: Int, lineEnd: Int,
            stmtType: String, stmtLabel: String,
            elseLine: Int, inCatch: Boolean
        ): Unit = {
          val stmtId = s"$basename:$lineStart"
          emit(jrow("flow",
            "func_name"  -> funcName,
            "func_file"  -> funcFile,
            "stmt_id"    -> stmtId,
            "line_start" -> lineStart.toString,
            "line_end"   -> lineEnd.toString,
            "stmt_type"  -> stmtType,
            "stmt_label" -> stmtLabel,
            "else_line"  -> elseLine.toString,
            "in_catch"   -> (if (inCatch) "1" else "0")))
        }

        // ── Control structures ──────────────────────────────────────────────
        m.ast.collect { case cs: ControlStructure => cs }.foreach { cs =>
          val ls = cs.lineNumber.getOrElse(0)
          val le = lineEnd(cs, ls)
          val ic = isInCatch(cs)

          cs.controlStructureType match {

            case "IF" =>
              val cond   = cs.condition.code.headOption.getOrElse(cs.code)
              val elseL  = cs.whenFalse.lineNumber.headOption.getOrElse(0)
              addFlow(ls, le, "if", s"if ($cond)", elseL, ic)

            case "FOR" | "FOREACH" =>
              val label = cs.code.split("\\{").headOption.getOrElse(cs.code).trim
              addFlow(ls, le, "for", label, 0, ic)

            case "WHILE" =>
              val cond = cs.condition.code.headOption.getOrElse("")
              addFlow(ls, le, "while", s"while ($cond)", 0, ic)

            case "DO_WHILE" =>
              val cond = cs.condition.code.headOption.getOrElse("")
              addFlow(ls, le, "do", s"do ... while ($cond)", 0, ic)

            case "TRY" =>
              val catchLines = cs.astChildren.collect {
                case c: ControlStructure if c.controlStructureType == "CATCH" => c
              }.flatMap(_.lineNumber.toList)
              val catchLine = if (catchLines.nonEmpty) catchLines.min else 0
              addFlow(ls, le, "try", "try", catchLine, ic)

            case "THROW" =>
              val expr  = cs.astChildren.code.headOption.getOrElse("")
              val label = if (expr.nonEmpty) s"throw $expr" else "throw"
              addFlow(ls, le, "throw", label, 0, ic)

            case "BREAK" =>
              addFlow(ls, le, "break", "break", 0, ic)

            case "CONTINUE" =>
              addFlow(ls, le, "continue", "continue", 0, ic)

            case "SWITCH" =>
              val cond = cs.condition.code.headOption.getOrElse("")
              addFlow(ls, le, "if", s"switch ($cond)", 0, ic)

            case "CATCH" | "FINALLY" | "ELSE" => // handled via parent nodes

            case _ => // unknown — skip
          }
        }

        // ── Return statements ───────────────────────────────────────────────
        m.ast.collect { case r: Return => r }.foreach { r =>
          val ls    = r.lineNumber.getOrElse(0)
          val le    = lineEnd(r, ls)
          val ic    = isInCatch(r)
          val label = if (r.code.startsWith("return")) r.code else s"return ${r.code}".trim
          addFlow(ls, le, "return", label, 0, ic)
        }

        // ── Throw expressions (Call node with <operator>.throw) ──────────────
        m.ast.collect { case c: Call if c.name == "<operator>.throw" => c }.foreach { c =>
          val ls    = c.lineNumber.getOrElse(0)
          val le    = lineEnd(c, ls)
          val ic    = isInCatch(c)
          val expr  = c.argument.code.headOption.getOrElse("")
          val label = if (expr.nonEmpty) s"throw $expr" else "throw"
          addFlow(ls, le, "throw", label, 0, ic)
        }

      } // end foreach method

  } finally {
    bw.close()
  }

  println(s"[joern] PHP analysis complete. Output written to: $outputPath")
}
