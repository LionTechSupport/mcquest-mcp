"use strict";

/**
 * READ-ONLY TypeScript/TSX/JS/JSX syntax diagnostic driver for mcquest-mcp.
 *
 * Invoked ONLY by the mcquest_diagnostics tool handler:
 *
 *     node diagnose.js --root <PROJECT_ROOT> --tslib <TS_LIB> --file <RELATIVE_PATH>
 *
 * The source text of the target file is provided on stdin. The driver:
 *
 *   - loads ONLY the validated project-local TypeScript compiler library
 *     (node_modules/typescript/lib/typescript.js) via require()
 *   - parses the source with ts.createSourceFile (a pure parser: no module
 *     resolution, no type checking, no tsconfig, no application code)
 *   - emits a bounded JSON document on stdout
 *
 * It never writes files, never resolves imports, never executes application
 * code, and never touches the network. Errors are emitted as `{ok:false}`
 * JSON with exit code 0 so the Python side can format them; unexpected
 * crashes produce a non-zero exit code.
 */

const fs = require("fs");
const path = require("path");

function emit(payload) {
  process.stdout.write(JSON.stringify(payload));
}

function fail(code, message, detail) {
  const payload = { ok: false, error: { code: code, message: message } };
  if (detail !== undefined) {
    payload.error.detail = detail;
  }
  emit(payload);
  process.exit(0);
}

function main() {
  const args = process.argv.slice(2);

  let rootArg = null;
  let tslibArg = null;
  let fileArg = null;

  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--root") {
      rootArg = args[++i];
    } else if (args[i] === "--tslib") {
      tslibArg = args[++i];
    } else if (args[i] === "--file") {
      fileArg = args[++i];
    } else if (args[i] === "--help") {
      process.stdout.write(
        "Usage: node diagnose.js --root <ROOT> --tslib <TS_LIB> --file <RELATIVE>\n"
      );
      process.exit(0);
    } else {
      fail("USAGE", "Unsupported argument: " + args[i]);
    }
  }

  if (!rootArg || !tslibArg || !fileArg) {
    fail("USAGE", "Missing required argument (--root, --tslib, --file).");
  }

  // Path containment (defense in depth): the compiler library must live
  // inside the project root. The Python handler already validates this; the
  // driver re-checks so a mis-invocation can never load an arbitrary library.
  const root = path.resolve(rootArg);
  const tslib = path.resolve(tslibArg);

  const rel = path.relative(root, tslib);
  if (rel === "" || rel.startsWith("..") || path.isAbsolute(rel)) {
    fail("PATH_ESCAPE", "TypeScript library is outside the project root.");
    return;
  }

  let sourceText;
  try {
    sourceText = fs.readFileSync(0, "utf-8");
  } catch (error) {
    fail("STDIN", "Could not read source text from stdin.", String(error));
    return;
  }

  let ts;
  try {
    ts = require(tslib);
  } catch (error) {
    fail("TS_LOAD", "Could not load project-local TypeScript library.", String(error));
    return;
  }

  const fileName = fileArg;

  // Infer the script kind from the file extension (mirrors the TypeScript
  // compiler's own behavior for .ts/.tsx/.js/.jsx).
  const kinds = ts.ScriptKind || {};
  let scriptKind;
  const lower = fileName.toLowerCase();
  if (lower.endsWith(".tsx")) {
    scriptKind = kinds.TSX;
  } else if (lower.endsWith(".jsx")) {
    scriptKind = kinds.JSX;
  } else if (lower.endsWith(".js") || lower.endsWith(".mjs") || lower.endsWith(".cjs")) {
    scriptKind = kinds.JS;
  } else {
    // .ts, .mts, .cts, .d.ts and anything else TypeScript treats as TS.
    scriptKind = kinds.TS;
  }

  let sourceFile;
  try {
    sourceFile = ts.createSourceFile(
      fileName,
      sourceText,
      ts.ScriptTarget.Latest,
      true,
      scriptKind
    );
  } catch (error) {
    fail("PARSE", "TypeScript could not parse the source.", String(error));
    return;
  }

  function messageText(text) {
    if (ts.flattenDiagnosticMessageText) {
      try {
        return ts.flattenDiagnosticMessageText(text, "\n");
      } catch (ignore) {
        // fall through to String()
      }
    }
    return String(text);
  }

  function position(diagFile, pos) {
    const lc = ts.getLineAndCharacterOfPosition(diagFile, pos);
    return { line: lc.line + 1, column: lc.character + 1 };
  }

  const MAX_EMITTED = 500;

  const diagnostics = [];
  for (const diagnostic of sourceFile.parseDiagnostics || []) {
    if (diagnostics.length >= MAX_EMITTED) {
      break;
    }

    const item = {
      code: diagnostic.code,
      severity: String(ts.DiagnosticCategory[diagnostic.category] || "Error").toLowerCase(),
      message: messageText(diagnostic.messageText),
      line: position(sourceFile, diagnostic.start).line,
      column: position(sourceFile, diagnostic.start).column,
      length: diagnostic.length || 0,
    };

    if (diagnostic.relatedInformation && diagnostic.relatedInformation.length) {
      item.related = [];
      for (const related of diagnostic.relatedInformation) {
        if (!related.file || typeof related.start !== "number") {
          continue;
        }
        const relPos = position(related.file, related.start);
        item.related.push({
          file: related.file.fileName,
          line: relPos.line,
          column: relPos.column,
          message: messageText(related.messageText),
        });
      }
    }

    diagnostics.push(item);
  }

  emit({
    ok: true,
    file: fileArg,
    scriptKindName: ts.ScriptKind[scriptKind] || path.extname(fileName).slice(1),
    typeScriptVersion: ts.version || "unknown",
    diagnostics: diagnostics,
  });
  process.exit(0);
}

main();