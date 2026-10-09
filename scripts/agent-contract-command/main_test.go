package main

import (
  "bytes"
  "encoding/json"
  "fmt"
  "io"
  "os"
  "path/filepath"
  "reflect"
  "strings"
  "testing"
)

func observe(t *testing.T, input string) (result, int, string) {
  t.Helper()
  var stdout, stderr bytes.Buffer
  status := run(strings.NewReader(input), &stdout, &stderr)
  t.Logf("input=%s stdout=%s stderr=%q exit=%d", input, strings.TrimSpace(stdout.String()), stderr.String(), status)
  var got result
  if status == 0 {
    decoder := json.NewDecoder(&stdout)
    decoder.DisallowUnknownFields()
    if err := decoder.Decode(&got); err != nil { t.Fatal(err) }
    var extra any
    if err := decoder.Decode(&extra); err != io.EOF { t.Fatalf("extra stdout JSON: %v", err) }
  } else if stdout.Len() != 0 {
    t.Fatalf("failed parse must not emit success JSON: %s", stdout.String())
  }
  return got, status, stderr.String()
}

func command(t *testing.T, text string) result {
  t.Helper()
  input, err := json.Marshal(map[string]string{"command": text})
  if err != nil { t.Fatal(err) }
  got, status, stderr := observe(t, string(input))
  if status != 0 { t.Fatalf("unexpected parse failure: %s", stderr) }
  if got.Pathspecs == nil { t.Fatal("pathspecs must be an array, not null") }
  return got
}

func TestApprovedReadOnlyAndData(t *testing.T) {
  tests := []string{
    `repos=$(find "$HOME/code" -maxdepth 2 -name .git -type d | xargs -I{} sh -c 'cd "$1" && pwd -P' sh {}); printf "%s\n" "$repos" | while IFS= read -r repo; do commits=$(git -C "$repo" log --branches --since="24 hours ago" --format="%H %s"); printf "%s\n" "$commits"; done`,
    `git log --format=%s --grep commit`,
    `printf '%s\n' 'sh -c git commit'`,
    "python3 - <<'PY'\ntext = 'sh -c git commit'\nprint(text)\nPY",
    `sh -c 'git log --grep commit'`,
    `printf '%s' 'G=git; "$G" commit -m text'`,
    "# \"unmatched git commit\nprintf foo#bar",
    `git -c alias.foo=commit log --grep=commit`,
    `command -v git commit`,
    "python3 - <<'EOF'\n$(git commit) `git commit`\nEOF",
    `printf '%s' '\$(git commit)'`,
    `node script.js commit`,
    `python3 script.py git commit`,
    `printf 'cd /bad; git -C /bad commit --all'`,
    `sh -c 'cd /other; git log --grep commit'; git status`,
  }
  for i, text := range tests {
    t.Run(fmt.Sprintf("readonly_%02d", i), func(t *testing.T) {
      got := command(t, text)
      if got.HasCommit || got.Denial != nil || got.CDTarget != nil || got.GitCTarget != nil || got.AutoStage || len(got.Pathspecs) != 0 {
        t.Fatalf("data/read-only polluted classification: %+v", got)
      }
    })
  }
}

func TestNestedStagingChangesOuterCommitIndex(t *testing.T) {
  for _, text := range []string{
    `git commit -m "$(git add agents/bad.md; printf note)"`,
    `sh -c 'git add agents/bad.md'; git commit -m note`,
    `printf agents/bad.md | xargs git add; git commit -m note`,
  } {
    t.Run(text, func(t *testing.T) {
      got := command(t, text)
      if !got.HasCommit || (!got.AutoStage && got.Denial == nil) {
        t.Fatalf("nested staging must not reuse the original index: %+v", got)
      }
    })
  }
}

func TestFunctionStagingAndXargsReadonly(t *testing.T) {
  t.Run("function staging", func(t *testing.T) {
    got := command(t, `stage() { git add .claude/agents/bad.md; }; stage; git commit -m note`)
    if !got.HasCommit || (!got.AutoStage && got.Denial == nil) {
      t.Fatalf("function staging lost index mutation: %+v", got)
    }
  })
  t.Run("readonly repo argument", func(t *testing.T) {
    got := command(t, `printf /repo | xargs -I{} git -C {} log`)
    if got.HasCommit || got.Denial != nil { t.Fatalf("readonly repo argument: %+v", got) }
  })
  t.Run("dynamic subcommand remains denied", func(t *testing.T) {
    got := command(t, `printf commit | xargs -I{} git {}`)
    if got.Denial == nil { t.Fatal("replacement can become the commit subcommand") }
  })
}

func TestRealCommitAndQuoteBoundaries(t *testing.T) {
  tests := []string{
    `git commit -m 'document sh -c git commit without executing it'`,
    `(git commit -m real)`,
    `{ git commit -m real; }`,
    `/usr/bin/git commit -m real`,
    `command git commit -m real`,
    `command -- git commit -m real`,
    `exec git commit -m real`,
    `env X=y git commit -m real`,
    `"git" 'commit' -m real`,
    `g"it" co'mm'it -m real`,
    `g\it com\mit -m real`,
    "$'git' $'commit' -m real",
    "# \"unmatched\ngit commit -m real",
    "# 'unmatched\ngit commit -m real",
    `printf foo#bar; git commit -m real`,
    "printf '%s' \"foo\nbar\"#literal && git commit -m real",
    "printf \\\"\ngit commit -m real",
    "printf \\\n\"foo\" && git commit -m real",
    "printf \"foo\\\\\nbar\" && git commit -m real",
    "git commit -m \"release notes\ngit add .claude/x\nend\"",
    `git commit -m "prefix \" git add spec"`,
    "g\\\nit com\\\nmit -m real",
    `if true; then git commit -m real; fi`,
  }
  for i, text := range tests {
    t.Run(fmt.Sprintf("commit_%02d", i), func(t *testing.T) {
      got := command(t, text)
      if !got.HasCommit || got.Denial != nil || got.AutoStage || len(got.Pathspecs) != 0 {
        t.Fatalf("real commit classification: %+v", got)
      }
    })
  }
}

func TestProtectedEntrances(t *testing.T) {
  tests := []struct{ text, denial string; commit bool }{
    {`bash -c 'git commit -m nested'`, "nested shell commit command", true},
    {`/bin/bash -lc 'git commit -m nested'`, "nested shell commit command", true},
    {`zsh -c 'git commit -m nested'`, "nested shell commit command", true},
    {`sh -c 'sh -c "git commit -m nested"'`, "nested shell commit command", true},
    {`printf "%s" "$(git commit -m nested)"`, "command-substitution commit command", true},
    {"printf '%s' `git commit -m nested`", "command-substitution commit command", true},
    {"cat <<EOF\n$(git commit -m nested)\nEOF", "command-substitution commit command", true},
    {`cat <(git commit -m nested)`, "process-substitution commit command", true},
    {`G=git; "$G" commit -m dynamic`, "dynamic Git executable", false},
    {`"${GIT_BIN}" commit -m dynamic`, "dynamic Git executable", false},
    {`git "$action" -m dynamic`, "dynamic Git subcommand", false},
    {`git $args commit -m dynamic`, "dynamic Git subcommand", false},
    {`eval 'git commit -m dynamic'`, "eval command", false},
    {`sh -c "$cmd"`, "dynamic shell command", false},
    {`sh "$flag" 'git commit'`, "dynamic shell option", false},
    {`GIT_DIR=/repo/.git git commit -m selector`, "Git selector", true},
    {`GIT_INDEX_FILE=/index; git commit -m selector`, "Git selector", true},
    {`export GIT_DIR=/repo/.git; git commit -m selector`, "Git selector", true},
    {`declare GIT_INDEX_FILE=/index; git commit -m selector`, "Git selector", true},
    {`env GIT_DIR="$repo" git commit -m selector`, "Git selector", true},
    {`env GIT_WORK_TREE=/repo git commit -m selector`, "Git selector", true},
    {`git --git-dir=/repo/.git commit -m selector`, "Git selector", true},
    {`git --work-tree /repo commit -m selector`, "Git selector", true},
    {`cd /; cd /repo; git commit -m real`, "multiple cd targets; the entire command was not executed", true},
    {`git -C /repo status; git -C /repo commit -m real`, "multiple git -C targets", true},
    {`git -C /repo -C sub commit -m real`, "multiple git -C targets", true},
    {`cd '/repo'; git commit -m real`, "quoted cd target", true},
    {`git -C "/repo" commit -m real`, "quoted git -C target", true},
    {`cd "$repo"; git commit -m real`, "quoted cd target", true},
    {`cd $repo; git commit -m real`, "dynamic cd target", true},
    {`git -C $repo commit -m real`, "dynamic git -C target", true},
    {`git commit -m real "$path"`, "dynamic commit pathspec", true},
    {`git commit -m real; cd /other`, "cd target after commit", true},
  }
  for i, tt := range tests {
    t.Run(fmt.Sprintf("protected_%02d", i), func(t *testing.T) {
      got := command(t, tt.text)
      if got.HasCommit != tt.commit || got.Denial == nil || !strings.Contains(*got.Denial, tt.denial) {
        t.Fatalf("want commit=%v denial=%q; got %+v", tt.commit, tt.denial, got)
      }
    })
  }
}

func TestAutoStageAndPathspecs(t *testing.T) {
  tests := []struct{ text string; auto bool; paths []string }{
    {`git add .claude/a; git commit -m real`, true, []string{}},
    {`git stage .claude/a && git commit -m real`, true, []string{}},
    {`git commit -a -m real`, true, []string{}},
    {`git commit -am 'add note'`, true, []string{}},
    {`git commit --all -m real`, true, []string{}},
    {`git commit --include .claude/a`, true, []string{".claude/a"}},
    {`git commit --only .claude/a`, true, []string{".claude/a"}},
    {`git commit --interactive`, true, []string{}},
    {`git commit --patch`, true, []string{}},
    {`git commit -p`, true, []string{}},
    {`git commit -i .claude/a`, true, []string{".claude/a"}},
    {`git commit -o .claude/a`, true, []string{".claude/a"}},
    {`git commit -- .claude/a`, true, []string{".claude/a"}},
    {`git commit -m 'touch .claude/a later'`, false, []string{}},
    {`git commit -m real .claude/a && git status .claude/b`, false, []string{".claude/a"}},
    {`git commit -F .claude/message README.md`, false, []string{"README.md"}},
    {`git commit --message=note --file=msg --author 'Name <x@y>' --date yesterday --cleanup strip --fixup HEAD --squash HEAD --trailer x:y --template msg --reuse-message HEAD --reedit-message HEAD README.md`, false, []string{"README.md"}},
    {`git commit -mnote -Fmsg -CHEAD -cHEAD -tmsg README.md`, false, []string{"README.md"}},
    {`git commit -m real '.claude/with space'`, false, []string{".claude/with space"}},
    {`git log --grep add; git commit -m 'git add -a --all'`, false, []string{}},
    {`git commit -m real; printf '%s' 'git add .claude/a'`, false, []string{}},
  }
  for i, tt := range tests {
    t.Run(fmt.Sprintf("argv_%02d", i), func(t *testing.T) {
      got := command(t, tt.text)
      if !got.HasCommit || got.Denial != nil || got.AutoStage != tt.auto || !reflect.DeepEqual(got.Pathspecs, tt.paths) {
        t.Fatalf("want auto=%v paths=%v; got %+v", tt.auto, tt.paths, got)
      }
    })
  }
}

func TestRepoContextDoesNotComeFromDataOrNestedReadOnly(t *testing.T) {
  tests := []struct{ text, cd, gitc string }{
    {`(cd /repo && git commit -m real)`, "/repo", ""},
    {`cd /repo && git commit -m 'note (cd /other; git -C /other commit)'`, "/repo", ""},
    {`git -C /repo commit -m 'cd /other'`, "", "/repo"},
    {`sh -c 'cd /other; git -C /other log --grep commit'; git commit -m real`, "", ""},
    {`printf '%s' "$(cd /other; git -C /other log --grep commit)"; git commit -m real`, "", ""},
    {`git -C/repo commit -m real`, "", "/repo"},
    {`git -c user.name=commit commit -m real`, "", ""},
  }
  for i, tt := range tests {
    t.Run(fmt.Sprintf("context_%02d", i), func(t *testing.T) {
      got := command(t, tt.text)
      value := func(p *string) string { if p == nil { return "" }; return *p }
      if !got.HasCommit || got.Denial != nil || value(got.CDTarget) != tt.cd || value(got.GitCTarget) != tt.gitc {
        t.Fatalf("repo context mismatch: %+v", got)
      }
    })
  }
}

func TestScopeAndWrapperBoundaries(t *testing.T) {
  tests := []struct{ text, cd, gitc, denial string; commit bool }{
    {`git -C /other log; git commit -m real`, "", "", "", true},
    {`git commit -m real; git -C /other log`, "", "", "", true},
    {`(cd /other; pwd); git commit -m real`, "", "", "", true},
    {`(git -C /other log); git commit -m real`, "", "", "", true},
    {`(cd /other; git commit -m real); git commit -m real`, "", "", "mixed shell scope", true},
    {`git -C /other commit -m real; git commit -m real`, "", "", "multiple commit repository contexts", true},
    {`git -C=/repo commit -m real`, "", "=/repo", "", true},
    {`git -C'/repo' commit -m real`, "", "", "quoted git -C target", true},
    {`git commit -m "$(git log --grep commit)"`, "", "", "", true},
    {`printf '%s' "\$(git commit)"`, "", "", "", false},
    {"cat <<E\\OF\n$(git commit)\nEOF", "", "", "", false},
    {`xargs -I{} sh -c 'git commit -m nested'`, "", "", "nested shell commit command", true},
    {`xargs git commit -m real`, "", "", "xargs commit command", true},
    {`bash -s`, "", "", "shell stdin command", false},
    {`git commit -m real --pathspec-from-file=list`, "", "", "pathspec file", true},
    {`if test -d /other; then cd /other; fi; git commit -m real`, "", "", "conditional cd", true},
  }
  for i, tt := range tests {
    t.Run(fmt.Sprintf("scope_%02d", i), func(t *testing.T) {
      got := command(t, tt.text)
      value := func(p *string) string { if p == nil { return "" }; return *p }
      if got.HasCommit != tt.commit || value(got.Denial) != "" && tt.denial == "" || tt.denial != "" && !strings.Contains(value(got.Denial), tt.denial) {
        t.Fatalf("want commit=%v denial=%q; got %+v", tt.commit, tt.denial, got)
      }
      if tt.denial == "" && (value(got.CDTarget) != tt.cd || value(got.GitCTarget) != tt.gitc) { t.Fatalf("wrong repo context: %+v", got) }
    })
  }
}

func TestAttachedDynamicTargetsAndDeclarationBoundary(t *testing.T) {
  tests := []struct{ text, denial string; commit bool }{
    {`git -C"$repo" commit -m real`, "quoted git -C target", true},
    {`git -C$repo commit -m real`, "dynamic git -C target", true},
    {`git --git-dir="$repo" commit -m real`, "Git selector", true},
    {`git -C/repo -Csub commit -m real`, "multiple git -C targets", true},
    {`(cd /other; git commit -m real); (git commit -m real)`, "mixed shell scope", true},
    {`if true; then command cd /other; fi; git commit -m real`, "conditional cd", true},
    {`f() { git commit -m real; }; f`, "shell function commit", false},
    {`g{it,it} commit -m real`, "dynamic Git executable", false},
    {`git com* -m real`, "dynamic Git subcommand", false},
    {`git commit -m real .claude/*`, "dynamic commit pathspec", true},
  }
  for i, tt := range tests {
    t.Run(fmt.Sprintf("attached_%02d", i), func(t *testing.T) {
      got := command(t, tt.text)
      if got.HasCommit != tt.commit || got.Denial == nil || !strings.Contains(*got.Denial, tt.denial) { t.Fatalf("want commit=%v denial=%q; got %+v", tt.commit, tt.denial, got) }
    })
  }
}

func TestLiteralShellRecursionIsBounded(t *testing.T) {
  nest := func(text string, count int) string {
    for i := 0; i < count; i++ {
      text = "sh -c '" + strings.ReplaceAll(text, "'", "'\\''") + "'"
    }
    return text
  }
  got := command(t, nest("pwd", 8))
  if got.HasCommit || got.Denial != nil { t.Fatalf("boundary must allow: %+v", got) }
  got = command(t, nest("git commit -m real", 8))
  if !got.HasCommit || got.Denial == nil || !strings.Contains(*got.Denial, "nested shell commit command") { t.Fatalf("boundary must protect: %+v", got) }
  got = command(t, nest("pwd", 9))
  if got.Denial == nil || !strings.Contains(*got.Denial, "recursion limit (8)") { t.Fatalf("limit must fail closed: %+v", got) }
}

func TestProtocolErrorsAreNotNoCommit(t *testing.T) {
  tests := []string{`{`, `null`, `[]`, `{}`, `{"command":null}`, `{"command":2}`, `{"command":true}`, `{"command":[]}`, `{"command":"pwd"} {}`, `{"command":"git commit -m '"}`, `{"command":"if true; then"}`}
  for i, text := range tests {
    t.Run(fmt.Sprintf("error_%02d", i), func(t *testing.T) {
      _, status, stderr := observe(t, text)
      if status == 0 || stderr == "" { t.Fatalf("must fail explicitly: exit=%d stderr=%q", status, stderr) }
    })
  }
}

func TestShellOptionArgumentsDoNotHideCommit(t *testing.T) {
  for _, text := range []string{`bash -o pipefail -c 'git commit -m nested'`, `bash -O extglob -c 'git commit -m nested'`} {
    got := command(t, text)
    if !got.HasCommit || got.Denial == nil || !strings.Contains(*got.Denial, "nested shell commit command") { t.Fatalf("option argument hid commit: %+v", got) }
  }
  got := command(t, `bash -o pipefail -c 'git log --grep commit'`)
  if got.HasCommit || got.Denial != nil { t.Fatalf("readonly nested shell was denied: %+v", got) }
  got = command(t, `bash --rcfile file -c 'git commit -m nested'`)
  if got.Denial == nil { t.Fatal("unsupported shell option must not silently hide -c") }
}

func TestInputIsNotExecutedOrRead(t *testing.T) {
  marker := filepath.Join(t.TempDir(), "must-not-exist")
  got := command(t, "git commit -F "+marker+"; touch "+marker)
  if !got.HasCommit || got.Denial != nil { t.Fatalf("unexpected classification: %+v", got) }
  if _, err := os.Stat(marker); !os.IsNotExist(err) { t.Fatalf("input executed: %v", err) }
}
