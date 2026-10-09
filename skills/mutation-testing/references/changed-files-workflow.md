# Changed-Files-Only Workflow

日常 CC 循環用——只跑 git-changed 檔的 mutation testing，避免每次 mutate 整個 repo 跑幾小時。

## 為什麼要這個變體

Full-repo mutation：mutant 上千個、跑幾小時、日常沒人跑。
Changed-files mutation：只 mutate 這次 diff 動到的 `.ts` / `.tsx` 檔、跑 30 秒到幾分鐘、日常可跑。

**Trade-off**：只跑 changed 檔的 mutation score **不能拿來當 CI break gate**——partial run 常有大量 `# no cov`（因為 test coverage cross-file、partial mutate 抓不到全景），會誤 fail。用來看**這次改的檔**盲點在哪就好。

## Setup

### 1. 額外的 stryker config

複製一份主 config，改兩件事：`mutate` 用 CLI 帶入、`thresholds.break` 設 null。

`stryker.conf.mutation-changed.json`：
```json
{
  "$schema": "./node_modules/@stryker-mutator/core/schema/stryker-schema.json",
  "packageManager": "yarn",
  "reporters": ["clear-text", "progress", "json"],
  "testRunner": "jest",
  "coverageAnalysis": "perTest",
  "jest": {
    "projectType": "custom",
    "configFile": "jest.config.js"
  },
  "concurrency": 4,
  "timeoutMS": 30000,
  "tempDirName": ".stryker-tmp",
  "thresholds": { "break": null },
  "ignorePatterns": [
    ".worktrees", ".shadow-cljs", "out", "proj-app",
    ".shopify", ".reports", ".cpcache", ".claude",
    ".next", "coverage", "logs", "src/gen"
  ]
}
```

**重點**：`thresholds.break: null` — partial run 分數低不代表 test suite 差、不 break。

### 2. Wrapper script

`scripts/stryker-mutate-changed.sh`（或 `.mjs`——選一種）：

```bash
#!/usr/bin/env bash
set -e

# Default: 對比 working tree vs HEAD（staged + unstaged + untracked）
BASE="${STRYKER_DIFF_BASE:-HEAD}"

if [ "$BASE" = "HEAD" ]; then
  # Working tree diff
  CHANGED=$(git diff --name-only HEAD -- '*.ts' '*.tsx' | grep -v '.test.' | grep -v '__tests__' | grep -v 'node_modules')
else
  # Branch scope: base...HEAD
  CHANGED=$(git diff --name-only "${BASE}...HEAD" -- '*.ts' '*.tsx' | grep -v '.test.' | grep -v '__tests__' | grep -v 'node_modules')
fi

if [ -z "$CHANGED" ]; then
  echo "No changed production .ts/.tsx files."
  exit 0
fi

echo "Mutating:"
echo "$CHANGED" | sed 's/^/  /'
echo ""

# Join with comma for --mutate
MUTATE_ARG=$(echo "$CHANGED" | paste -sd, -)

npx stryker run \
  --configFile stryker.conf.mutation-changed.json \
  --mutate "$MUTATE_ARG" \
  "$@"
```

`chmod +x scripts/stryker-mutate-changed.sh`。

### 3. Package.json script

```json
"scripts": {
  "mutate:changed": "bash scripts/stryker-mutate-changed.sh",
  "mutate:changed:list": "bash scripts/stryker-mutate-changed.sh --dryRunOnly"
}
```

## 使用

### 日常：跑 working tree diff

```bash
yarn mutate:changed
```

跑 staged + unstaged + untracked `.ts` / `.tsx` 檔的 mutation。

### PR-scope：跑 branch diff

```bash
STRYKER_DIFF_BASE=master yarn mutate:changed
```

跑「這個 branch 相對 master 的所有改動檔」——PR review 前跑一次很有用。

### 加速選項

- `--ignoreStatic`：跳過 static class member / module-level constant mutants（Jest 難 isolate、通常不重要）
- `--dryRunOnly`：只驗 setup 跑得起來、不真跑 mutant（debug 用）

## Troubleshooting

| 症狀 | 原因 | 動作 |
|---|---|---|
| `Initial test run timed out` | Jest 首次 dry-run 超時（大 project 常見） | 加 `--dryRunTimeoutMinutes 10` |
| `There were failed tests in the initial test run` | Baseline test 沒全綠 | 停下先修 test、baseline 綠了才跑 mutation |
| `No changed files under .ts/.tsx` | 這次改動只碰到 test / cljs / 非 TS 檔 | 正常、可跳 mutation stage |
| 大量 `# no cov`、分數超低 | Partial `--mutate` 抓不到 cross-file coverage | **預期行為**、不要跟 full-repo 分數 compare、只 review survivor |
| 跑超慢 | Mutant 多 + perTest coverage 貴 | `--ignoreStatic`、或縮 diff base 只跑最新 commit |

## 何時走這個變體 vs full-repo

| 情境 | 用哪個 |
|---|---|
| CC 剛寫完 test、我要驗品質 | changed-files（快、精準） |
| PR review 前驗 branch 整體 | changed-files with `STRYKER_DIFF_BASE=master` |
| 要 CI break gate 或整體 project 品質 | full-repo（不常跑、專案級 milestone） |
| Refactor 大改、想全面驗 | full-repo |
