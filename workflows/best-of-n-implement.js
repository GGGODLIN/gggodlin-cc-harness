export const meta = {
  name: 'best-of-n-implement',
  description: '同一實作 task 平行 N 個 worktree 候選 → 測試客觀淘汰 → judge 比 diff 品質 → 回傳勝者 diff（由呼叫端 git apply）',
  whenToUse: 'plan 內被使用者拍板標記 best-of-N 的高風險 task（解空間寬 / 核心模組 / 難回滾），或使用者臨時指定某段實作走 best-of-N。token 成本約 N 倍單 task，必須使用者點頭才跑。',
  phases: [
    { title: 'Implement', detail: 'N 個 agent 各自 worktree 實作同一 task' },
    { title: 'Judge', detail: '測試通過者之間比 diff 品質' },
  ],
}

const task = args?.task
const n = args?.n ?? 3
const testCmd = args?.testCmd
const repoPath = args?.repoPath
if (!task) return { error: 'args.task 必填：task 完整描述（含檔案路徑與驗收標準）；選填 args.n（預設 3）、args.testCmd（測試指令，強烈建議給）、args.repoPath（絕對路徑到 target git repo。target repo ≠ parent session cwd 時必給——harness 的 worktree 隔離只認 session cwd 那個 repo；給了之後改由各 candidate 自己在 target repo 內開 .worktrees/bon-<i>）' }

// repoPath 的隔離策略（2026-08-01 修）：Workflow script sandbox 沒有 Node API，
// `process.chdir` 直接炸 `process is not defined`；而 harness 的 isolation:'worktree'
// 一律從 parent session cwd 那個 repo 開 worktree、指不到別的 repo。所以 repoPath 一給，
// 就把隔離責任下移到 agent：它自己在 target repo 內開 detached worktree 並在裡面工作。
// 不給 repoPath 時維持原行為（harness worktree 隔離、session cwd 即 target repo）。
const REPO_SCOPE = (i) =>
  repoPath
    ? `\n\n## 工作目錄（絕對規則）\n先自己開隔離 worktree 再動手：\n\`\`\`bash\ncd ${repoPath}\ngit worktree add --detach .worktrees/bon-${i + 1} HEAD\n\`\`\`\n之後**所有**讀寫與測試都在 \`${repoPath}/.worktrees/bon-${i + 1}\` 內；絕不碰 ${repoPath} 本身或別的 .worktrees/*（其他候選正平行工作、互相踩會毀掉整輪）。\n若該 repo 的測試需要依賴（node_modules 等）而 worktree 內沒有，用 symlink 指回主 repo 那份、不要重裝。\n交付後**不要**自己移除 worktree（呼叫端要看 diff）；diff 用 \`git -C ${repoPath}/.worktrees/bon-${i + 1} add -N -- . && git -C ${repoPath}/.worktrees/bon-${i + 1} diff HEAD\` 取（含新檔）。`
    : `（你在 harness 配好的獨立 git worktree，直接改檔）`
if (repoPath) {
  log(`repoPath=${repoPath}：隔離下移到 agent（各自開 .worktrees/bon-<i>），不用 harness worktree isolation`)
}

phase('Implement')
const ANGLES = ['最小改動優先', '可讀性與既有 pattern 一致優先', '邊界條件與錯誤處理優先', '效能優先', '可測試性優先']
const IMPL_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    approach: { type: 'string', description: '一句話描述這版的取捨' },
    diff: { type: 'string', description: '完整 git diff' },
    testsPass: { type: 'boolean' },
    testOutput: { type: 'string', description: '測試輸出尾段' },
    notes: { type: 'string' },
  },
  required: ['approach', 'diff', 'testsPass'],
}

const candidates = await parallel(
  Array.from({ length: n }, (_, i) => () =>
    agent(
      `實作以下 task${repoPath ? '' : REPO_SCOPE(i)}。實作視角：${ANGLES[i % ANGLES.length]}——遇到取捨時往這個方向偏，但正確性永遠優先。${repoPath ? REPO_SCOPE(i) : ''}\n\nTASK:\n${task}\n\n完成後${testCmd ? `必跑 \`${testCmd}\`，testsPass 照實填，` : '跑你能找到的相關測試（找不到 → testsPass 填 false 並在 notes 說明），'}然後取完整 diff（含新增檔：先 \`git add -N -- .\` 再 \`git diff HEAD\`）。schema：approach 放取捨描述、diff 放完整 git diff、testOutput 放測試輸出尾段。誠實回報——測試沒過就填 false，judge 階段造假會被抓。\n\n禁止 git commit / merge / stash——成果只以 diff 回報。`,
      {
        label: `impl-${i + 1}`,
        phase: 'Implement',
        schema: IMPL_SCHEMA,
        model: 'opus',
        ...(repoPath ? {} : { isolation: 'worktree' }),
      }
    )
  )
)

const valid = candidates.filter(Boolean)
const passers = valid.filter((c) => c.testsPass)
log(`${valid.length}/${n} 個候選完成，${passers.length} 個通過測試`)

if (!passers.length) return {
    winner: null,
    candidates: valid,
    note:
      '無候選通過測試——全部 diff 附上供人工檢視，不要直接 apply' +
      (repoPath ? ` candidate worktree 在 ${repoPath}/.worktrees/bon-*、需自行清理。` : ''),
  }
if (passers.length === 1) return { winner: passers[0], losers: [], note: '唯一測試通過者，未經 judge 比較。apply 前自己 review diff。' }

phase('Judge')
const VERDICT = {
  type: 'object',
  additionalProperties: false,
  properties: {
    winnerIndex: { type: 'number', description: '最佳候選的「候選編號」（=== 候選 N === 標頭裡的 N）' },
    evidence: { type: 'string', description: '先產生這欄：逐候選列可觀察證據（指向具體 diff 行/邊界處理/測試輸出），不含結論' },
    reasoning: { type: 'string', description: '比較理由，含每個候選一句話評語' },
  },
  required: ['winnerIndex', 'evidence', 'reasoning'],
}
const labeled = passers.map((c, i) => ({ ...c, id: i }))
const judgePrompt = (list) =>
  `你是 code judge。以下 ${list.length} 個 diff 實作同一個 task 且都通過測試。先對每個候選列出可觀察證據（指向具體 diff 行/邊界處理/測試輸出），全部列完才下結論——證據先於評分。比較品質——正確性與邊界處理、與既有 codebase 慣例一致、簡潔不過度工程、可維護性——選出最佳；難分高下時偏好更簡單、改動更少的候選。\n\nTASK:\n${task}\n\n${list.map((c) => `=== 候選 ${c.id}（取捨：${c.approach}）===\n${c.diff}`).join('\n\n')}\n\nschema：winnerIndex 放最佳候選的候選編號、evidence 放逐候選證據、reasoning 放比較理由。`
const [passA, passB] = await parallel([
  () => agent(judgePrompt(labeled), { label: 'judge:pass1', phase: 'Judge', schema: VERDICT, model: 'opus', effort: 'high' }),
  () => agent(judgePrompt([...labeled].reverse()), { label: 'judge:pass2-swapped', phase: 'Judge', schema: VERDICT, model: 'opus', effort: 'high' }),
])

const wA = passA?.winnerIndex
const wB = passB?.winnerIndex
const diffLines = (c) => c.diff.split('\n').length
let wi
let judgeNote
if (wA != null && wA === wB && labeled[wA]) {
  wi = wA
  judgeNote = 'position-swap 雙 pass 一致'
} else {
  const contenders = [wA, wB].filter((x) => x != null && labeled[x]).map((x) => labeled[x])
  const pool = contenders.length ? contenders : labeled
  wi = pool.reduce((a, b) => (diffLines(a) <= diffLines(b) ? a : b)).id
  judgeNote = `position-swap 雙 pass 不一致（pass1=${wA} vs pass2=${wB}）→ 判平手、tie-breaker 取較簡單候選（diff 行數少者）。confidence 低，apply 前務必人工 review`
}
return {
  winner: passers[wi],
  verdict: { winnerIndex: wi, judgeNote, pass1: passA, pass2: passB },
  losers: passers.filter((_, i) => i !== wi).map((c) => ({ approach: c.approach })),
  note:
    '呼叫端把 winner.diff 經 git apply 落進真實 working tree，apply 後重跑測試確認。' +
    (repoPath ? ` 收尾：candidate worktree 留在 ${repoPath}/.worktrees/bon-*，apply 完自己 \`git worktree remove --force\`。` : ''),
}
