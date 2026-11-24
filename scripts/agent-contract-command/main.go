// This helper prevents drift, not deliberate same-UID evasion. It classifies
// supported shell AST entrances without executing input or reading named files.
// Unknown relevant entrances fail closed; scripts, aliases, variable evaluation,
// and arbitrary shell runtime semantics are outside its guarantee.
package main

import (
  "encoding/json"
  "fmt"
  "io"
  "os"
  "path"
  "strings"

  "mvdan.cc/sh/v3/expand"
  "mvdan.cc/sh/v3/syntax"
)

type result struct {
  HasCommit  bool     `json:"has_commit"`
  Denial     *string  `json:"denial"`
  CDTarget   *string  `json:"cd_target"`
  GitCTarget *string  `json:"git_c_target"`
  AutoStage  bool     `json:"auto_stage"`
  OnlyCommit bool     `json:"only_commit"`
  Pathspecs  []string `json:"pathspecs"`
}

// Literal shell -c recursion and AST substitution/scope descent share this bound.
const maxDepth = 8

type rejection struct { rank int; reason string }
type target struct { word *syntax.Word; pos uint; commit bool }
type span struct { start, end uint }
type inspection struct {
  result result
  rejections []rejection
  cds, gitcs []target
  selector, staged, indexMutation, funcCD, dirStack bool
  onlyFlag, otherAutoStage, amendFlag, nonCommitCall bool
  outerCommit, scopedCD bool
  conditionalRanges []span
  commits int
  firstCommit uint
  depth int
  err error
}

func (s *inspection) reject(rank int, reason string) {
  s.rejections = append(s.rejections, rejection{rank, reason})
}

func hasUnquotedGlobMeta(wps []syntax.WordPart) bool {
  openBracket := false
  bracketHasContent := false
  for _, p := range wps {
    switch p := p.(type) {
    case *syntax.Lit:
      escaped := false
      for i := 0; i < len(p.Value); i++ {
        c := p.Value[i]
        if escaped {
          escaped = false
          if openBracket { bracketHasContent = true }
          continue
        }
        if c == '\\' {
          escaped = true
          continue
        }
        if c == '*' || c == '?' { return true }
        if c == '[' {
          if openBracket { bracketHasContent = true }
          openBracket = true
          continue
        }
        if c == ']' && openBracket {
          if bracketHasContent { return true }
          bracketHasContent = true
          continue
        }
        if openBracket { bracketHasContent = true }
      }
    case *syntax.SglQuoted:
      if openBracket && len(p.Value) > 0 { bracketHasContent = true }
    case *syntax.DblQuoted:
      if openBracket && len(p.Parts) > 0 { bracketHasContent = true }
    }
  }
  return false
}

// Eligibility is structural. Expansion receives only literals, with filesystem,
// environment and execution callbacks unset. Brace/glob/parameter expansion is
// never evaluated; tilde targets remain text for the caller's existing resolver.
func literal(w *syntax.Word) (value string, quoted, ok bool) {
  if w == nil { return "", false, false }
  safe := !hasUnquotedGlobMeta(w.Parts)
  var parts func([]syntax.WordPart, bool)
  parts = func(wps []syntax.WordPart, inQuotes bool) {
    for _, p := range wps {
      switch p := p.(type) {
      case *syntax.Lit:
        if !inQuotes && strings.HasPrefix(p.Value, "~") { safe = false }
      case *syntax.SglQuoted:
        quoted = true
      case *syntax.DblQuoted:
        quoted = true
        if p.Dollar { safe = false }
        parts(p.Parts, true)
      default:
        safe = false
      }
    }
  }
  parts(w.Parts, false)
  copy := *w
  if syntax.SplitBraces(&copy) {
    syntax.Walk(&copy, func(n syntax.Node) bool {
      if _, expansion := n.(*syntax.BraceExp); expansion { safe = false; return false }
      return true
    })
  }
  if !safe { return "", quoted, false }
  fields, err := expand.Fields(&expand.Config{}, w)
  if err != nil || len(fields) != 1 { return "", quoted, false }
  return fields[0], quoted, true
}

func targetValue(w *syntax.Word, kind string) (string, string) {
  value, quoted, ok := literal(w)
  if quoted { return "", "quoted " + kind + " target" }
  if !ok && w != nil {
    if tilde, tildeOK := staticTildeValue(w, true); tildeOK { return tilde, "" }
  }
  if !ok { return "", "dynamic " + kind + " target" }
  if value == "" || strings.HasPrefix(value, "-") { return "", "unresolved " + kind + " target" }
  return value, ""
}

func parse(text string, lang syntax.LangVariant) (*syntax.File, error) {
  if strings.ContainsRune(text, 0) { return nil, fmt.Errorf("shell command contains NUL") }
  return syntax.NewParser(syntax.Variant(lang)).Parse(strings.NewReader(text), "stdin")
}

func classify(text string) (result, error) {
  tree, err := parse(text, syntax.LangBash)
  if err != nil { return result{}, err }
  s := inspect(tree, 0)
  return s.finish(), s.err
}

func inspect(node syntax.Node, depth int) *inspection {
  s := &inspection{result: result{Pathspecs: []string{}}, depth: depth}
  if depth > maxDepth {
    s.reject(5, "shell inspection recursion limit (8) exceeded")
    return s
  }
  syntax.Walk(node, func(n syntax.Node) bool {
    switch n := n.(type) {
    case *syntax.CallExpr:
      s.call(n)
    case *syntax.Assign:
      if n.Name != nil {
        if selectorAssignment(n.Name.Value) { s.selector = true }
      } else if n.Value != nil {
        value, _, ok := literal(n.Value)
        if !ok {
          s.selector = true
        } else if !strings.HasPrefix(value, "-") && !strings.HasPrefix(value, "+") {
          name, _, hasEq := strings.Cut(value, "=")
          if hasEq { name = strings.TrimSuffix(name, "+") }
          if selectorAssignment(name) { s.selector = true }
        }
      }
    case *syntax.CmdSubst:
      s.child(inspect(&syntax.File{Stmts: n.Stmts}, depth+1), "command-substitution commit command", 20)
      return false
    case *syntax.ProcSubst:
      s.child(inspect(&syntax.File{Stmts: n.Stmts}, depth+1), "process-substitution commit command", 20)
      return false
    case *syntax.Redirect:
      switch n.Op {
      case syntax.RdrOut, syntax.AppOut, syntax.RdrInOut, syntax.RdrClob, syntax.RdrAll, syntax.AppAll:
        s.nonCommitCall = true
      }
      // Quoted heredoc delimiters disable expansion; their bodies are data.
      if n.Hdoc != nil {
        _, quoted, _ := literal(n.Word)
        if !quoted && !strings.Contains(n.Word.Lit(), "\\") { syntax.Walk(n.Hdoc, s.expansionVisitor) }
        return false
      }
    case *syntax.Stmt:
      if n.Background {
        stmtCopy := *n
        stmtCopy.Background = false
        s.mergeScoped(inspect(&stmtCopy, depth+1))
        return false
      }
    case *syntax.CoprocClause:
      s.mergeScoped(inspect(n.Stmt, depth+1))
      return false
    case *syntax.BinaryCmd:
      switch n.Op {
      case syntax.Pipe, syntax.PipeAll:
        var stages []*syntax.Stmt
        var collect func(*syntax.Stmt)
        collect = func(st *syntax.Stmt) {
          if bin, ok := st.Cmd.(*syntax.BinaryCmd); ok && (bin.Op == syntax.Pipe || bin.Op == syntax.PipeAll) && len(st.Redirs) == 0 && !st.Background && !st.Coprocess && !st.Negated {
            collect(bin.X)
            collect(bin.Y)
            return
          }
          stages = append(stages, st)
        }
        collect(n.X)
        collect(n.Y)
        for _, st := range stages {
          s.mergeScoped(inspect(st, depth+1))
        }
        return false
      case syntax.AndStmt:
        s.conditionalRanges = append(s.conditionalRanges, span{n.Y.Pos().Offset(), n.Y.End().Offset()})
      case syntax.OrStmt:
        s.conditionalRanges = append(s.conditionalRanges, span{n.Pos().Offset(), n.End().Offset()})
      }
    case *syntax.Subshell:
      s.mergeScoped(inspect(&syntax.File{Stmts: n.Stmts}, depth+1))
      return false
    case *syntax.IfClause, *syntax.WhileClause, *syntax.ForClause, *syntax.CaseClause:
      s.conditionalRanges = append(s.conditionalRanges, span{n.Pos().Offset(), n.End().Offset()})
    case *syntax.FuncDecl:
      child := inspect(n.Body, depth+1)
      s.staged = s.staged || child.staged
      s.indexMutation = s.indexMutation || child.indexMutation
      s.selector = s.selector || child.selector
      s.dirStack = s.dirStack || child.dirStack
      if len(child.cds) > 0 || child.scopedCD || child.funcCD { s.funcCD = true }
      s.err = firstError(s.err, child.err)
      s.rejections = append(s.rejections, child.rejections...)
      if child.result.HasCommit { s.reject(15, "shell function commit command cannot be resolved") }
      return false
    }
    return true
  })
  return s
}

func (s *inspection) mergeScoped(child *inspection) {
  s.err = firstError(s.err, child.err)
  s.rejections = append(s.rejections, child.rejections...)
  s.staged = s.staged || child.staged
  s.indexMutation = s.indexMutation || child.indexMutation
  s.nonCommitCall = s.nonCommitCall || child.nonCommitCall
  if child.result.HasCommit {
    s.result.HasCommit = true
    s.result.AutoStage = s.result.AutoStage || child.result.AutoStage
    s.otherAutoStage = true
    s.result.Pathspecs = append(s.result.Pathspecs, child.result.Pathspecs...)
    s.cds = append(s.cds, child.cds...)
    s.gitcs = append(s.gitcs, child.gitcs...)
    s.scopedCD = s.scopedCD || child.scopedCD || len(child.cds) > 0
    s.conditionalRanges = append(s.conditionalRanges, child.conditionalRanges...)
    s.selector = s.selector || child.selector
    s.funcCD = s.funcCD || child.funcCD
    s.dirStack = s.dirStack || child.dirStack
    s.commits += child.commits
    if s.firstCommit == 0 { s.firstCommit = child.firstCommit }
  }
}

func firstError(a, b error) error {
  if a != nil { return a }
  return b
}

func (s *inspection) expansionVisitor(n syntax.Node) bool {
  switch n := n.(type) {
  case *syntax.CmdSubst:
    s.child(inspect(&syntax.File{Stmts: n.Stmts}, s.depth+1), "command-substitution commit command", 20)
    return false
  case *syntax.ProcSubst:
    s.child(inspect(&syntax.File{Stmts: n.Stmts}, s.depth+1), "process-substitution commit command", 20)
    return false
  }
  return true
}

func (s *inspection) child(child *inspection, reason string, rank int) {
  // 子 shell 的 cwd 不外溢，但 git add 修改的是共用 index。
  s.staged = s.staged || child.staged
  s.indexMutation = s.indexMutation || child.indexMutation
  s.nonCommitCall = s.nonCommitCall || child.nonCommitCall
  if child.err != nil { s.err = child.err }
  if child.result.HasCommit {
    s.result.HasCommit = true
    s.reject(rank, reason)
  } else {
    // 子 shell 的 cd/-C/selector 不能選定外層 repo。
    s.rejections = append(s.rejections, child.rejections...)
  }
}

func selectorAssignment(name string) bool {
  switch name {
  case "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_CONFIG", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS":
    return true
  }
  return strings.HasPrefix(name, "GIT_CONFIG_KEY_") || strings.HasPrefix(name, "GIT_CONFIG_VALUE_")
}

func (s *inspection) call(call *syntax.CallExpr) {
  for _, assign := range call.Assigns {
    if assign.Name != nil && selectorAssignment(assign.Name.Value) { s.selector = true }
  }
  args := call.Args
  if len(args) == 0 {
    s.nonCommitCall = true
    return
  }
  viaExternal := false
  for len(args) > 0 {
    executable, _, ok := literal(args[0])
    if !ok {
      s.reject(30, "dynamic Git executable cannot be classified")
      return
    }
    hasSlash := strings.Contains(executable, "/")
    executable = path.Base(executable)
    switch executable {
    case "command", "builtin", "exec":
      if executable == "exec" { viaExternal = true }
      args = args[1:]
      if len(args) > 0 {
        option, _, static := literal(args[0])
        if !static { s.reject(30, "dynamic execution wrapper"); return }
        if executable == "command" && (option == "-v" || option == "-V") { return }
        if option == "--" || (executable == "command" && option == "-p") { args = args[1:] }
        if len(args) > 0 {
          next, _, _ := literal(args[0])
          if executable == "command" && option == "-p" && next == "--" {
            args = args[1:]
          } else if strings.HasPrefix(next, "-") {
            s.reject(30, "unsupported execution wrapper option"); return
          }
        }
      }
      continue
    case "env":
      viaExternal = true
      args = args[1:]
      for len(args) > 0 {
        value, _, static := literal(args[0])
        if !static {
          if len(args[0].Parts) > 0 {
            if prefix, ok := args[0].Parts[0].(*syntax.Lit); ok {
              name, _, assignment := strings.Cut(prefix.Value, "=")
              if assignment && selectorAssignment(name) { s.selector = true; args = args[1:]; continue }
            }
          }
          s.reject(30, "dynamic execution wrapper")
          return
        }
        if value == "--" { args = args[1:]; break }
        if value == "-i" || value == "--ignore-environment" { args = args[1:]; continue }
        if value == "-u" || value == "--unset" {
          if len(args) < 2 { s.reject(30, "missing env option value"); return }
          args = args[2:]; continue
        }
        if strings.HasPrefix(value, "-") { s.reject(30, "unsupported env execution wrapper"); return }
        name, _, assignment := strings.Cut(value, "=")
        if !assignment { break }
        if selectorAssignment(name) { s.selector = true }
        args = args[1:]
      }
      continue
    case "xargs":
      s.nonCommitCall = true
      s.xargs(args[1:])
    case "eval":
      s.nonCommitCall = true
      s.reject(20, "eval command cannot be classified without execution")
    case "sh", "bash", "zsh":
      s.nonCommitCall = true
      s.shell(executable, args[1:])
    case "git":
      s.git(args[1:])
    case "cd":
      if viaExternal || hasSlash {
        s.nonCommitCall = true
        return
      }
      var word *syntax.Word
      if len(args) > 1 {
        word = args[1]
        if value, _, _ := literal(word); value == "--" && len(args) > 2 { word = args[2] }
      }
      s.cds = append(s.cds, target{word: word, pos: call.Pos().Offset()})
    case "pushd", "popd":
      s.nonCommitCall = true
      if !viaExternal && !hasSlash { s.dirStack = true }
    default:
      s.nonCommitCall = true
    }
    return
  }
}

func (s *inspection) xargs(args []*syntax.Word) {
  if s.depth >= maxDepth { s.reject(5, "shell inspection recursion limit (8) exceeded"); return }
  replacement := ""
  for len(args) > 0 {
    option, _, ok := literal(args[0])
    if !ok { s.reject(30, "dynamic xargs command cannot be classified"); return }
    if option == "--" { args = args[1:]; break }
    if !strings.HasPrefix(option, "-") { break }
    if len(option) < 2 { s.reject(30, "unsupported xargs option"); return }
    for j := 1; j < len(option); j++ {
      flag := option[j]
      if strings.ContainsRune("EIRSJLnPs", rune(flag)) {
        var value string
        if j+1 < len(option) { value = option[j+1:] } else {
          if len(args) < 2 { s.reject(30, "missing xargs option value"); return }
          args = args[1:]
          var known bool
          value, _, known = literal(args[0])
          if !known { s.reject(30, "dynamic xargs option value"); return }
        }
        if flag == 'I' || flag == 'J' { replacement = value }
        break
      }
      if !strings.ContainsRune("0optx", rune(flag)) { s.reject(30, "unsupported xargs option"); return }
    }
    args = args[1:]
  }
  if len(args) == 0 { return }
  executable, _, ok := literal(args[0])
  if !ok || replacement != "" && strings.Contains(executable, replacement) { s.reject(30, "dynamic xargs executable"); return }
  executable = path.Base(executable)
  forwarded := append([]*syntax.Word{}, args...)
  if replacement != "" {
    for i, arg := range forwarded {
      value, _, known := literal(arg)
      if known && strings.Contains(value, replacement) {
        // 只標示未知 argv；由既有 Git/shell 判讀區分入口與 repo 等資料。
        forwarded[i] = &syntax.Word{Parts: []syntax.WordPart{&syntax.ParamExp{Param: &syntax.Lit{Value: "XARGS_INPUT"}}}}
      }
    }
  } else {
    forwarded = append(forwarded, &syntax.Word{Parts: []syntax.WordPart{&syntax.ParamExp{Param: &syntax.Lit{Value: "XARGS_INPUT"}}}})
  }
  child := &inspection{result: result{Pathspecs: []string{}}, depth: s.depth+1}
  child.call(&syntax.CallExpr{Args: forwarded})
  s.staged = s.staged || child.staged
  s.indexMutation = s.indexMutation || child.indexMutation
  s.err = firstError(s.err, child.err)
  s.rejections = append(s.rejections, child.rejections...)
  if child.result.HasCommit {
    s.result.HasCommit = true
    s.reject(10, "xargs commit command cannot inspect its input arguments")
  }
}

// staticTildeValue reports whether w is a static ~/... (or ~ when allowBare)
// path without variables, globs, or brace expansions, returning the unescaped path.
func staticTildeValue(w *syntax.Word, allowBare bool) (string, bool) {
  if w == nil || hasUnquotedGlobMeta(w.Parts) { return "", false }
  safe := true
  var raw strings.Builder
  var parts func([]syntax.WordPart)
  parts = func(wps []syntax.WordPart) {
    for _, p := range wps {
      switch p := p.(type) {
      case *syntax.Lit:
        raw.WriteString(p.Value)
      case *syntax.SglQuoted:
        raw.WriteString(p.Value)
      case *syntax.DblQuoted:
        if p.Dollar { safe = false }
        parts(p.Parts)
      default:
        safe = false
      }
    }
  }
  parts(w.Parts)
  copy := *w
  if syntax.SplitBraces(&copy) {
    syntax.Walk(&copy, func(n syntax.Node) bool {
      if _, expansion := n.(*syntax.BraceExp); expansion { safe = false; return false }
      return true
    })
  }
  rawStr := raw.String()
  if !safe || (!(allowBare && rawStr == "~") && !strings.HasPrefix(rawStr, "~/")) { return "", false }
  if rawStr == "~" { return "~", true }
  if len(w.Parts) > 0 {
    if lit, ok := w.Parts[0].(*syntax.Lit); ok && strings.HasPrefix(lit.Value, "~/") {
      litCopy := *lit
      litCopy.Value = lit.Value[1:]
      wordCopy := *w
      wordCopy.Parts = append([]syntax.WordPart{&litCopy}, w.Parts[1:]...)
      fields, err := expand.Fields(&expand.Config{}, &wordCopy)
      if err != nil || len(fields) != 1 { return "", false }
      return "~" + fields[0], true
    }
  }
  return rawStr, true
}

func staticTildePath(w *syntax.Word) bool {
  _, ok := staticTildeValue(w, false)
  return ok
}

func (s *inspection) shell(executable string, args []*syntax.Word) {
  hasC := false
  readStdin := false
  operandIdx := len(args)
  for i := 0; i < len(args); i++ {
    option, _, ok := literal(args[i])
    if !ok {
      if !hasC && !readStdin && staticTildePath(args[i]) { return }
      if hasC {
        s.reject(10, "dynamic shell command cannot be classified")
      } else {
        s.reject(10, "dynamic shell option or command cannot be classified")
      }
      return
    }
    if option == "--" || option == "-" {
      operandIdx = i + 1
      break
    }
    if !strings.HasPrefix(option, "-") && !strings.HasPrefix(option, "+") {
      operandIdx = i
      break
    }
    if option == "-o" || option == "+o" || option == "-O" || option == "+O" {
      i++
      if i >= len(args) { s.reject(10, "missing shell option value"); return }
      if _, _, ok := literal(args[i]); !ok { s.reject(10, "dynamic shell option value"); return }
      continue
    }
    if strings.HasPrefix(option, "+") { s.reject(10, "unsupported shell option cannot be classified"); return }
    if strings.HasPrefix(option, "--") {
      if option == "--norc" || option == "--noprofile" { continue }
      s.reject(10, "unsupported shell option cannot be classified")
      return
    }
    for _, flag := range option[1:] {
      if !strings.ContainsRune("abefhkmnptuvxBCHPirsDlc", flag) { s.reject(10, "unsupported shell option cannot be classified"); return }
      if flag == 'c' { hasC = true }
      if flag == 's' { readStdin = true }
    }
  }
  if hasC {
    if operandIdx >= len(args) { s.reject(10, "missing shell -c command"); return }
    text, _, ok := literal(args[operandIdx])
    if !ok { s.reject(10, "dynamic shell command cannot be classified"); return }
    if s.depth >= maxDepth { s.reject(5, "shell inspection recursion limit (8) exceeded"); return }
    lang := syntax.LangBash
    if executable == "sh" { lang = syntax.LangPOSIX }
    if executable == "zsh" { lang = syntax.LangZsh }
    tree, err := parse(text, lang)
    if err != nil { s.err = fmt.Errorf("nested %s syntax: %w", executable, err); return }
    s.child(inspect(tree, s.depth+1), "nested shell commit command", 10)
    return
  }
  if !readStdin && operandIdx < len(args) { return }
  s.reject(10, "shell stdin command cannot be classified without execution")
}

// Split only an AST literal prefix, retaining the target's quote/expansion nodes.
func attachedWord(w *syntax.Word, prefix string) *syntax.Word {
  if len(w.Parts) == 0 { return nil }
  first, ok := w.Parts[0].(*syntax.Lit)
  if !ok || !strings.HasPrefix(first.Value, prefix) { return nil }
  rest := strings.TrimPrefix(first.Value, prefix)
  if rest == "" && len(w.Parts) == 1 { return nil }
  parts := append([]syntax.WordPart{}, w.Parts[1:]...)
  if rest != "" {
    copy := *first
    copy.Value = rest
    parts = append([]syntax.WordPart{&copy}, parts...)
  }
  return &syntax.Word{Parts: parts}
}

func (s *inspection) git(args []*syntax.Word) {
  cStart := len(s.gitcs)
  for i := 0; i < len(args); i++ {
    if word := attachedWord(args[i], "-C"); word != nil {
      s.gitcs = append(s.gitcs, target{word: word, pos: args[i].Pos().Offset()})
      continue
    }
    selector := false
    for _, prefix := range []string{"--git-dir=", "--work-tree=", "--namespace=", "--config-env=", "--super-prefix="} {
      if attachedWord(args[i], prefix) != nil { selector = true }
    }
    if selector { s.selector = true; continue }
    if word := attachedWord(args[i], "-c"); word != nil {
      config, _, known := literal(word)
      if !known || strings.HasPrefix(strings.ToLower(config), "core.worktree=") || strings.HasPrefix(strings.ToLower(config), "core.bare=") { s.selector = true }
      continue
    }
    value, _, ok := literal(args[i])
    if !ok { s.reject(30, "dynamic Git subcommand or option cannot be classified"); return }
    if value == "--" { continue }
    if !strings.HasPrefix(value, "-") {
      switch value {
      case "commit":
        s.result.HasCommit = true
        s.outerCommit = true
        s.commits++
        for j := cStart; j < len(s.gitcs); j++ { s.gitcs[j].commit = true }
        if s.firstCommit == 0 { s.firstCommit = args[i].Pos().Offset()+1 }
        s.commitArgs(args[i+1:])
      case "add", "stage":
        s.staged = true
        s.nonCommitCall = true
      case "rm", "mv", "update-index", "read-tree", "apply":
        s.staged = true
        s.indexMutation = true
        s.nonCommitCall = true
      default:
        s.nonCommitCall = true
      }
      return
    }
    if strings.HasPrefix(value, "-C") && len(value) > 2 {
      _, quoted, _ := literal(args[i])
      var part syntax.WordPart = &syntax.Lit{Value: value[2:]}
      if quoted { part = &syntax.SglQuoted{Value: value[2:]} }
      s.gitcs = append(s.gitcs, target{word: &syntax.Word{Parts: []syntax.WordPart{part}}, pos: args[i].Pos().Offset()})
      continue
    }
    name, attached, hasAttached := strings.Cut(value, "=")
    switch name {
    case "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--super-prefix":
      var word *syntax.Word
      if hasAttached { word = &syntax.Word{Parts: []syntax.WordPart{&syntax.Lit{Value: attached}}} } else {
        i++
        if i >= len(args) { s.reject(30, "missing Git option value"); return }
        word = args[i]
      }
      if name == "-C" { s.gitcs = append(s.gitcs, target{word: word, pos: args[i].Pos().Offset()}) }
      if name != "-C" && name != "-c" { s.selector = true }
      if name == "-c" || name == "--config-env" {
        config, _, known := literal(word)
        if !known || strings.HasPrefix(strings.ToLower(config), "core.worktree=") || strings.HasPrefix(strings.ToLower(config), "core.bare=") { s.selector = true }
      }
    case "--bare":
      s.selector = true
    case "-v", "--version", "-h", "--help", "--html-path", "--man-path", "--info-path":
      return
    case "--exec-path":
      if !hasAttached { return }
    case "-p", "--paginate", "-P", "--no-pager", "--no-replace-objects", "--literal-pathspecs", "--noglob-pathspecs", "--no-optional-locks", "--no-lazy-fetch", "--no-advice":
    case "--glob-pathspecs", "--icase-pathspecs":
      s.otherAutoStage = true
    default:
      if strings.HasPrefix(value, "-c") && len(value) > 2 {
        if strings.HasPrefix(strings.ToLower(value[2:]), "core.worktree=") || strings.HasPrefix(strings.ToLower(value[2:]), "core.bare=") { s.selector = true }
      } else { s.reject(30, "unsupported Git global option cannot be classified"); return }
    }
  }
}

func (s *inspection) commitArgs(args []*syntax.Word) {
  paths := false
  values := map[string]bool{"--message":true, "--file":true, "--reuse-message":true, "--reedit-message":true, "--author":true, "--date":true, "--template":true, "--cleanup":true, "--fixup":true, "--squash":true, "--trailer":true}
  flags := map[string]bool{"--quiet":true, "--verbose":true, "--reset-author":true, "--signoff":true, "--edit":true, "--status":true, "--verify":true, "--dry-run":true, "--short":true, "--branch":true, "--ahead-behind":true, "--porcelain":true, "--long":true, "--null":true, "--amend":true, "--post-rewrite":true, "--allow-empty":true, "--allow-empty-message":true}
  for i := 0; i < len(args); i++ {
    value, _, ok := literal(args[i])
    if !ok { s.reject(90, "dynamic commit pathspec or option cannot be classified"); continue }
    if !paths && value == "--" { paths = true; s.result.AutoStage = true; continue }
    if paths || !strings.HasPrefix(value, "-") || value == "-" {
      s.result.Pathspecs = append(s.result.Pathspecs, value)
      continue
    }
    if strings.HasPrefix(value, "--") {
      name, _, attached := strings.Cut(value, "=")
      positive := strings.TrimPrefix(name, "--no-")
      if positive != name { positive = "--" + positive } else { positive = name }
      switch name {
      case "--only":
        s.result.AutoStage = true
        s.onlyFlag = true
      case "--no-only":
        s.onlyFlag = false
        s.otherAutoStage = true
      case "--all", "--include", "--interactive", "--patch":
        s.result.AutoStage = true
        s.otherAutoStage = true
      case "--pathspec-from-file", "--pathspec-file-nul":
        s.result.AutoStage = true
        s.otherAutoStage = true
        s.reject(90, "commit pathspec file cannot be inspected without reading input files")
      default:
        if name == "--amend" { s.amendFlag = true }
        if values[name] {
          if !attached {
            i++
            if i >= len(args) { s.reject(90, "missing commit option value") }
          }
        } else if values[positive] {
          if attached { s.reject(90, "unsupported commit option cannot be classified") }
        } else if flags[positive] || positive == "--gpg-sign" || positive == "--untracked-files" || positive == "--all" || positive == "--include" || positive == "--only" || positive == "--interactive" || positive == "--patch" {
        } else { s.reject(90, "unsupported commit option cannot be classified") }
      }
      continue
    }
    for j := 1; j < len(value); j++ {
      switch value[j] {
      case 'o':
        s.result.AutoStage = true
        s.onlyFlag = true
      case 'a', 'i', 'p':
        s.result.AutoStage = true
        s.otherAutoStage = true
      case 'm', 'F', 'C', 'c', 't':
        if j == len(value)-1 {
          i++
          if i >= len(args) { s.reject(90, "missing commit option value") }
        }
        j = len(value)
      case 'S', 'u':
        // Optional arguments are attached, not the following pathspec.
        j = len(value)
      case 'q', 'v', 's', 'e', 'n', 'z':
      default:
        s.reject(90, "unsupported commit option cannot be classified")
      }
    }
  }
}

func (s *inspection) finish() result {
  if s.result.HasCommit {
    s.result.AutoStage = s.result.AutoStage || s.staged
    s.result.OnlyCommit = s.commits == 1 && s.onlyFlag && !s.otherAutoStage && !s.amendFlag && !s.staged && !s.nonCommitCall && len(s.result.Pathspecs) > 0
    if s.indexMutation { s.reject(35, "index-mutating git command before commit cannot be safely inspected") }
    if s.selector { s.reject(40, "command-local Git selector cannot be safely inspected") }
    if s.funcCD { s.reject(55, "shell function cd target cannot select one commit repository") }
    if s.dirStack { s.reject(55, "directory stack builtin cannot select one commit repository") }
    if (s.outerCommit || s.commits > 1) && s.scopedCD { s.reject(55, "mixed shell scope cd targets cannot select one commit repository") }
    for _, t := range s.cds {
      for _, r := range s.conditionalRanges {
        if t.pos >= r.start && t.pos < r.end { s.reject(55, "conditional cd target cannot select one commit repository") }
      }
    }
    if s.commits > 1 {
      for _, t := range s.gitcs {
        if t.commit { s.reject(65, "multiple commit repository contexts cannot be represented") }
      }
    }
    if len(s.cds) > 1 { s.reject(50, "multiple cd targets; the entire command was not executed") }
    if len(s.gitcs) > 1 { s.reject(60, "multiple git -C targets") }
    if len(s.cds) == 1 {
      value, reason := targetValue(s.cds[0].word, "cd")
      if reason != "" { s.reject(70, reason) } else { s.result.CDTarget = &value }
      if s.firstCommit > 0 && s.cds[0].pos >= s.firstCommit { s.reject(65, "cd target after commit cannot select its repository") }
    }
    if len(s.gitcs) == 1 && s.gitcs[0].commit {
      value, reason := targetValue(s.gitcs[0].word, "git -C")
      if reason != "" { s.reject(80, reason) } else { s.result.GitCTarget = &value }
    }
  } else {
    s.result.AutoStage = false
    s.result.Pathspecs = []string{}
  }
  for _, r := range s.rejections {
    if s.result.Denial == nil { value := r.reason; s.result.Denial = &value }
  }
  best := 1000
  for _, r := range s.rejections {
    if r.rank < best { best = r.rank; value := r.reason; s.result.Denial = &value }
  }
  return s.result
}

func run(stdin io.Reader, stdout, stderr io.Writer) int {
  fail := func(err error) int {
    fmt.Fprintf(stderr, "agent-contract-command: %v\n", err)
    return 1
  }
  decoder := json.NewDecoder(stdin)
  var input map[string]json.RawMessage
  if err := decoder.Decode(&input); err != nil { return fail(err) }
  var extra any
  if err := decoder.Decode(&extra); err != io.EOF { return fail(fmt.Errorf("expected exactly one JSON object")) }
  raw, ok := input["command"]
  if !ok || len(raw) == 0 || raw[0] != '"' { return fail(fmt.Errorf("command must be a JSON string")) }
  var text string
  if err := json.Unmarshal(raw, &text); err != nil { return fail(err) }
  output, err := classify(text)
  if err != nil { return fail(err) }
  if err := json.NewEncoder(stdout).Encode(output); err != nil { return fail(err) }
  return 0
}

func main() { os.Exit(run(os.Stdin, os.Stdout, os.Stderr)) }
