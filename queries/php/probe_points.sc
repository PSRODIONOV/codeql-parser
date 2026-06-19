// queries/php/probe_points.sc
// Joern v2 script: extracts sensor insertion points for PHP dynamic instrumentation.
//
// For each non-external PHP method/function emits:
//   kind=entry  — line of the first statement in the method body
//   kind=branch — line of the first statement inside each if/else/loop/try/catch branch
//
// Output: JSONL to the file given by `out` parameter.
//
// Invoked by instrument_php.py via temp-script injection:
//   joern --script <temp_copy_with_injected_vals>

import io.shiftleft.codepropertygraph.generated.nodes._
import io.shiftleft.semanticcpg.language._
import java.io.{BufferedWriter, FileWriter}

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

  def jrow(kvs: (String, Any)*): String =
    "{" + kvs.map { case (k, v) =>
      val vs = v match {
        case i: Int    => i.toString
        case l: Long   => l.toString
        case s: String => jstr(s)
        case _         => jstr(v.toString)
      }
      jstr(k) + ":" + vs
    }.mkString(",") + "}"

  def matches(path: String): Boolean =
    pattern.isEmpty || path.contains(pattern)

  // ── Import PHP source ─────────────────────────────────────────────────────
  try {
    importCode.php(inputPath)
  } catch {
    case _: Exception => importCode(inputPath, language = "PHP")
  }

  val bw = new BufferedWriter(new FileWriter(outputPath, false))
  def emit(line: String): Unit = { bw.write(line); bw.newLine() }

  // ── Emit a single probe point ─────────────────────────────────────────────
  def emitProbe(
      kind: String, func: String, file: String,
      refLine: Int, insLine: Int, insCol: Int, btype: String
  ): Unit = {
    if (insLine > 0) {
      emit(jrow(
        "kind"      -> kind,
        "func"      -> func,
        "file"      -> file,
        "ref_line"  -> refLine,
        "ins_line"  -> insLine,
        "ins_col"   -> insCol,
        "has_block" -> 1,
        "btype"     -> btype
      ))
    }
  }

  // ── First statement line inside a node's direct AST children ─────────────
  // Skips Local nodes (declarations without a real source line in the body).
  def firstChildLine(block: AstNode): Option[(Int, Int)] = {
    block.astChildren.l
      .filterNot(_.isInstanceOf[Local])
      .flatMap(n => n.lineNumber.map(ln => (ln, n.columnNumber.getOrElse(0))))
      .sortBy(_._1)
      .headOption
  }

  try {
    cpg.method
      .filterNot(_.isExternal)
      .filter(m => matches(m.filename))
      .filterNot(m => m.name.startsWith("<") || m.name.isEmpty)
      .foreach { m =>
        val fname   = m.fullName
        val file    = m.filename
        val mLine   = m.lineNumber.getOrElse(1)

        // ── Entry probe: first statement of the method body ─────────────────
        firstChildLine(m.body).foreach { case (ln, col) =>
          emitProbe("entry", fname, file, mLine, ln, col, "entry")
        }

        // ── Branch probes: control structures inside the method ─────────────
        m.ast.collect { case cs: ControlStructure => cs }.foreach { cs =>
          val csLine = cs.lineNumber.getOrElse(0)
          if (csLine > 0) {
            cs.controlStructureType match {

              case "IF" =>
                // True branch
                cs.whenTrue.headOption.foreach { tb =>
                  firstChildLine(tb).foreach { case (ln, col) =>
                    emitProbe("branch", fname, file, csLine, ln, col, "true")
                  }
                }
                // False branch (else / elseif)
                cs.whenFalse.headOption.foreach { fb =>
                  firstChildLine(fb).foreach { case (ln, col) =>
                    emitProbe("branch", fname, file, csLine, ln, col, "false")
                  }
                }

              case "FOR" | "FOREACH" | "WHILE" | "DO_WHILE" =>
                cs.whenTrue.headOption.foreach { body =>
                  firstChildLine(body).foreach { case (ln, col) =>
                    emitProbe("branch", fname, file, csLine, ln, col, "loop")
                  }
                }

              case "TRY" =>
                // Try body (first BLOCK child that is not CATCH/FINALLY)
                val tryBlocks = cs.astChildren.l.collect {
                  case b: Block => b
                }.headOption
                tryBlocks.foreach { tb =>
                  firstChildLine(tb).foreach { case (ln, col) =>
                    emitProbe("branch", fname, file, csLine, ln, col, "try")
                  }
                }
                // Catch bodies
                cs.astChildren.l.collect {
                  case c: ControlStructure if c.controlStructureType == "CATCH" => c
                }.foreach { cc =>
                  val ccLine = cc.lineNumber.getOrElse(csLine)
                  cc.astChildren.l.collect { case b: Block => b }.headOption.foreach { body =>
                    firstChildLine(body).foreach { case (ln, col) =>
                      emitProbe("branch", fname, file, ccLine, ln, col, "catch")
                    }
                  }
                }

              case _ => // BREAK, CONTINUE, THROW, SWITCH, etc. — no body to probe
            }
          }
        }
      }
  } finally {
    bw.close()
  }

  println(s"[probe_points] PHP probe extraction complete. Output: $outputPath")
}
