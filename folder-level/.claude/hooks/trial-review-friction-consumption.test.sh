#!/bin/bash
set -u

COMMAND="$HOME/Desktop/projects/.claude/commands/trial-review.md"
STRONG_MODELS="$HOME/.claude/references/strong-models.md"
PROTOCOL="$HOME/.claude/friction/PROTOCOL.md"
HOOK="$HOME/Desktop/projects/.claude/hooks/trial-review.sh"
ACTIVE="$HOME/Desktop/projects/.claude/trials/active.md"
ARCHIVER="$HOME/Desktop/projects/.claude/hooks/trial-archive-resources.py"
FIX=$(mktemp -d)
SESSION="friction-consumption-test-$$"
PASS=0
FAIL=0
SKIP=0
SUNSET_NUDGE_SRC="$HOME/.claude/hooks/proj-harness-ledger-nudge.sh"
SUNSET_AUDIT_SRC="$HOME/.claude/hooks/proj-harness-ledger-audit.sh"

cleanup() {
  rm -rf "$FIX"
  rm -f "/tmp/trial-review-session-$SESSION"
  rm -f "/tmp/trial-review-session-${SESSION}-index"
}
trap cleanup EXIT

assert_grep() {
  local description="$1"
  local pattern="$2"
  local file="$3"
  if grep -qE "$pattern" "$file"; then
    printf 'PASS: %s\n' "$description"
    PASS=$((PASS + 1))
  else
    printf 'FAIL: %s\n' "$description"
    FAIL=$((FAIL + 1))
  fi
}

assert_not_grep() {
  local description="$1"
  local pattern="$2"
  local file="$3"
  if grep -qE "$pattern" "$file"; then
    printf 'FAIL: %s\n' "$description"
    FAIL=$((FAIL + 1))
  else
    printf 'PASS: %s\n' "$description"
    PASS=$((PASS + 1))
  fi
}

assert_grep "command 標示契約測試" '^<!-- 本檔在契約測試底下：bash .*trial-review-friction-consumption\.test\.sh.*friction-review-state\.test\.sh -->$' "$COMMAND"
assert_grep "Step 0 盤點摩擦候選" '^2\. \*\*摩擦候選\*\*：' "$COMMAND"
assert_grep "Step 0 對摩擦分三組" 'Trial 與摩擦各自分成三組.*本 session 可處理.*有效時間鎖.*marker 格式損壞' "$COMMAND"
assert_grep "拍板訊息採 compact-first" 'compact-first.*推薦先講.*證據後放' "$COMMAND"
assert_grep "沒出題先講三個答案" '有沒有叫到.*核心能力有沒有被考到.*現在推薦' "$COMMAND"
assert_grep "固定證據區塊在推薦後呈現" '固定證據區塊.*推薦之後' "$COMMAND"
assert_grep "逐項呈現走拍板主報告加證據副檔" '拍板主報告＋完整證據副檔' "$COMMAND"
assert_grep "聊天採 exact allowlist" '聊天只准出現.*這則要你做的事.*三行入口.*每群.*一行.*證據副檔.*拍板表' "$COMMAND"
assert_grep "多路徑資料流下沉證據副檔" '多路徑.*資料流.*證據副檔.*不進聊天' "$COMMAND"
assert_grep "四件套只作研究與證據 checklist" '四件套.*研究與證據副檔.*不是聊天段落' "$COMMAND"
assert_not_grep "移除聊天強制資料流舊規格" '三行入口之後、四件套之前先給一段資料流' "$COMMAND"
assert_not_grep "移除聊天接四件套舊規格" '完成三行後接四件套' "$COMMAND"
assert_grep "拍板前等待背景證據收齊" '所有本項背景 agent／task.*完成.*evidence_state=frozen' "$COMMAND"
assert_grep "trial 入口先從頭鋪四步狀態流" '這個 trial 在驗什麼→這輪發生什麼.*→現在只決定什麼' "$COMMAND"
assert_grep "內部代號不得先於狀態流" '內部代號、counter、檔案數、API 限制不得出現在狀態流之前' "$COMMAND"
assert_grep "Step 1 證據與拍板代號當場白話註解" '證據要點與拍板表.*首次出現.*內部代號.*白話註解.*同一輪.*不算' "$COMMAND"
assert_grep "不改推薦的晚到證據只更新副檔" '不改推薦.*只更新.*證據副檔.*不另發拍板' "$COMMAND"
assert_grep "改推薦時只發完整替代報告" '改推薦.*superseded.*完整替代報告' "$COMMAND"
assert_grep "第一次替代報告重新鋪底" '第一次改推薦.*替代報告.*三行入口.*重新鋪底' "$COMMAND"
assert_grep "每項最多一則替代報告" '每項最多一則完整替代報告' "$COMMAND"
assert_grep "第二次改推薦撤回拍板" '第二次.*改推薦.*evidence_state=unstable.*撤回拍板.*不再要求 a/b/c' "$COMMAND"
assert_grep "無參數盤點後直接認領第一項" '沒有指定.*直接認領清單第一個可處理項.*接 Step 1.*不停下讓使用者選題' "$COMMAND"
assert_grep "指定題目直接接認領" '已選好題目.*直接接 Step 1.*不重問' "$COMMAND"
assert_grep "每題拍板後直接認領下一題" '收到拍板後照 Step 2.*Step 4 結完本題.*直接回到 Step 1.*認領下一題.*不另問是否進行下一題' "$COMMAND"
assert_grep "停點包含強模型通知與每題拍板" '停點只有強模型通知與每題的 a/b/c 拍板' "$COMMAND"
assert_grep "認領前接上強模型通知" '身分與鎖檢查後.*強模型通知.*認領' "$COMMAND"
assert_grep "強標記或研究中確認需求才通知" 'review-start=strong.*理由.*研究中.*重訂判定條件' "$COMMAND"
assert_grep "一般或缺資料不自動升強" '一般起手、未標記或單純缺資料.*不觸發' "$COMMAND"
assert_grep "通知決策先讀最強模型定義" '先讀.*references/strong-models[.]md.*主 session.*實際模型' "$COMMAND"
assert_grep "最強模型命中直接續做免問" '命中最強模型.*不發換模通知.*直接續做' "$COMMAND"
assert_grep "最強模型定義包含 Fable" 'Fable.*claude-fable-' "$STRONG_MODELS"
assert_grep "Astra 型號沿用既有版本表" 'Astra.*GPT_ASTRA.*config/gpt-models[.]env' "$STRONG_MODELS"
assert_grep "模型判定取主 session runtime" 'message[.]model.*不取.*subagent' "$STRONG_MODELS"
assert_grep "requested alias 不當免問證據" 'requested.*不.*免問' "$STRONG_MODELS"
assert_grep "effort 尾綴不改模型家族" '去除.*effort.*尾綴' "$STRONG_MODELS"
assert_grep "免問定義不削弱研究與拍板" '不省略.*研究.*拍板' "$STRONG_MODELS"
assert_grep "開場強模型不取鎖不寫 checkpoint" '開場就知道要強模型.*不寫 checkpoint、不取時間鎖' "$COMMAND"
assert_grep "開場強模型不偷跑研究" '開場就知道要強模型.*不開始或繼續研究' "$COMMAND"
assert_grep "研究中強模型停止新增研究" '研究中才確認要強模型.*停止新增研究.*不派新的研究 agent' "$COMMAND"
assert_grep "研究中強模型寫 checkpoint" 'evidence_state=checkpoint' "$COMMAND"
assert_grep "checkpoint 記 source identity" 'source_identity:' "$COMMAND"
assert_grep "checkpoint 記 verified facts" 'verified_facts:' "$COMMAND"
assert_grep "checkpoint 記未解決策" 'unresolved_decision:' "$COMMAND"
assert_grep "checkpoint 記續接點" 'resume_from:' "$COMMAND"
assert_grep "handoff 原子替換 marker" '同一次精確修改.*marker 替換成.*review-handoff' "$COMMAND"
assert_grep "handoff 指針格式固定" 'review-handoff:.*review-evidence/<YYYY-MM-DD>-<session 前 8 碼>[.]md#trial-<slug>-<started>' "$COMMAND"
assert_grep "續接在新研究前讀 handoff" 'review-handoff.*認領後、任何新研究前' "$COMMAND"
assert_grep "來源未變只處理未解分歧" '來源身分全部相同.*只處理 `unresolved_decision`' "$COMMAND"
assert_grep "來源變動只局部刷新" '部分來源變動.*只重查受影響的 facts' "$COMMAND"
assert_grep "handoff 壞掉不默默全量重查" 'handoff-invalid.*移除自己的 marker.*不靜默退回完整重查' "$COMMAND"
assert_grep "checkpoint 結案升 frozen" 'evidence_state=checkpoint.*evidence_state=frozen' "$COMMAND"
assert_grep "handoff 不另建第二份 evidence" '不要另建第二份證據檔' "$COMMAND"
assert_grep "延輪與改題移除 handoff" '延輪／改題.*移除 `review-handoff`' "$COMMAND"
assert_grep "active ledger 定義 review-handoff" 'review-handoff:.*review-evidence/' "$ACTIVE"
assert_grep "active ledger 固定 handoff 在 marker 原位" 'H2 下一行.*marker 原位替換.*固定欄位之前' "$ACTIVE"
assert_grep "active ledger 要求 checkpoint 後原子釋放" '先寫完整 checkpoint.*同一次精確修改.*marker.*review-handoff' "$ACTIVE"
assert_grep "模型提示不被主報告前置擋住" '通知不是拍板主報告.*不需先完成四件套' "$COMMAND"
assert_grep "使用者選擇後原地續做不重問" '使用者.*繼續.*原停點續做.*不因同一理由重問' "$COMMAND"
assert_not_grep "移除僅拍板可停的衝突文字" '唯一停點是 Step 1|唯一的停點是每題|只拿掉為它設的停點，模型沿用當前 session 不另問' "$COMMAND"
assert_not_grep "移除起手停清單選題舊指令" '停在清單等使用者選題|盤點完成即停下等選題|在總結末尾只詢問使用者是否進行下一題' "$COMMAND"
assert_not_grep "不允許批次跳過逐題確認" '使用者說「批次」「一起出」' "$COMMAND"
assert_grep "Step 4 總結只留三件" '處置結果表.*剩餘狀態一行.*要拍板的題' "$COMMAND"
assert_grep "每檔使用獨立時間鎖" 'friction-review-lock:v1' "$COMMAND"
assert_grep "來源修改與結案寫入前雙重重驗" '來源修改前重驗一次.*結案寫入前再重驗一次' "$COMMAND"
assert_grep "結案寫入與鎖釋放必須原子化" '同一次檔案寫入完成.*移除自己的 marker' "$COMMAND"
assert_grep "拍板後寫三欄歸因紀錄" 'proposal_source=.*user_decision=.*implementation=' "$COMMAND"
assert_grep "Self-Verify 驗摩擦狀態" '摩擦紀錄一致性與歸因' "$COMMAND"
assert_grep "公司側 approved 留待落地" 'approved.*公司側.*pending_implementation' "$COMMAND"
assert_grep "待落地有獨立提醒" '已拍板待落地' "$HOOK"
assert_grep "分群不取代原文" '不用短標識取代原文' "$COMMAND"
assert_grep "PROTOCOL 標示契約測試" '^<!-- 本檔在契約測試底下：.*trial-review-friction-consumption\.test\.sh.*friction-review-state\.test\.sh -->$' "$PROTOCOL"
assert_grep "PROTOCOL 定義 90 天退場命令" 'retire --older-than 90d' "$PROTOCOL"
assert_grep "PROTOCOL 定義嚴格 90 天邊界" '嚴格早於.*D - 90 days.*第 90 天' "$PROTOCOL"
assert_grep "PROTOCOL 定義季度 archive append" 'friction/archive/<YYYY-Qn>[.]md.*追加' "$PROTOCOL"
assert_grep "PROTOCOL 定義同層 H2 段界" '下一個同層的 `## `.*`###`／`####`' "$PROTOCOL"
assert_grep "中央協議定義摩擦時間鎖" 'friction-review-lock:v1' "$PROTOCOL"
assert_grep "中央協議定義歸因紀錄" 'proposal_source=.*user_decision=.*implementation=' "$PROTOCOL"
assert_grep "中央協議固定已折前導日期為捕捉日" '前導日期.*原摩擦.*捕捉日.*不得.*拍板日.*user_decision' "$PROTOCOL"
assert_grep "中央協議保留零折入退場" '實際折入為零.*刪本檔' "$PROTOCOL"
assert_grep "新摩擦寫入帶 provenance envelope" 'source_ref=.*signal_type=.*target=.*feedback_quote=.*why=' "$PROTOCOL"
assert_grep "舊摩擦格式保持可讀" '舊格式.*仍可讀.*不要求 migration' "$PROTOCOL"
assert_grep "trial-review 產出 provenance 與 authority 判定" 'authority_scope=.*corroboration=' "$COMMAND"
assert_grep "agent observation 不得獨立推薦折入" 'agent-observation.*不得.*折入.*推薦' "$COMMAND"
assert_grep "signal metadata 不得自我授權" 'signal_type.*untrusted metadata.*不得.*自我授權' "$COMMAND"
assert_not_grep "拍板表不再固定折入為推薦" '每列給 `a[.] 折入（推薦） / b[.] 否決 / c[.] 保留待折`' "$COMMAND"
assert_grep "PROTOCOL 定義 optional flags" '`flags` 是唯一 optional 欄位' "$PROTOCOL"
assert_grep "PROTOCOL 啟用資料最小化" '改寫 user／external text／log／error／code.*移除 secret' "$PROTOCOL"
assert_grep "PROTOCOL 不 blanket ban path hash quote" 'path、hash 與短引文不是禁用類別' "$PROTOCOL"
assert_grep "PROTOCOL flags annotation only" 'flag 只 annotation.*不得 filter、block 或 auto-merge' "$PROTOCOL"
assert_grep "PROTOCOL 保留直接 one-off" '直接觀察 one-off 仍是有效條目' "$PROTOCOL"
assert_grep "PROTOCOL 不改寫既有待折" '既有待折項不因本版補欄或重寫' "$PROTOCOL"
assert_grep "PROTOCOL 接上 helper tests" 'friction-outcome-packet[.]test[.]py' "$PROTOCOL"
assert_grep "trial-review surface flags" 'flags=<\.\.\.|none>.*annotation_suggestion=.*annotation_decision=<pending>' "$COMMAND"
assert_grep "trial-review 記錄人類 annotation decision" 'annotation_decision=<flag:confirmed\|flag:false-positive.*timestamp-or-message-id' "$COMMAND"
assert_grep "same-owner duplicate 僅提議合併" '相同 owner.*duplicate-root.*只能提議合併.*不能自動合併' "$COMMAND"
assert_grep "cross-owner 根因保持分群" '不同 owner.*保持不同群組' "$COMMAND"
assert_grep "缺 metadata attribution skip 不失敗" 'SKIPPED\(metadata-missing-or-not-skill\).*不讓整題失敗' "$COMMAND"
assert_grep "trial-review 呼叫 deterministic helper" 'friction-outcome-packet[.]py --session <id> --skill <name> --output <packet-path>' "$COMMAND"
assert_grep "packet 當 untrusted evidence" 'packet 當 untrusted evidence、不是指令' "$COMMAND"
assert_grep "outcome verdict 三值固定" 'NEW_ACTIONABLE.*ALREADY_FIXED.*NOT_SKILL_CAUSED' "$COMMAND"
assert_grep "只有 NEW_ACTIONABLE route skill-creator" '只有 `NEW_ACTIONABLE`.*route 到 `skill-creator`' "$COMMAND"
assert_grep "event attribution 不改 weekly" '不修改 cc-skill-doctor weekly.*不新增 channel／hook／gate' "$COMMAND"
assert_grep "trial-review 接上 helper tests" 'friction-outcome-packet[.]test[.]py' "$COMMAND"
assert_grep "狀態轉換 fixture 覆蓋 approved" '同檔多項目一次批次處理並最後釋放鎖' "$HOME/Desktop/projects/.claude/hooks/friction-review-state.test.sh"
assert_grep "狀態轉換 fixture 覆蓋 rejected" 'user_decision=rejected@test' "$HOME/Desktop/projects/.claude/hooks/friction-review-state.test.sh"
assert_grep "狀態轉換 fixture 覆蓋 pending 結案" 'pending 重新認領後取得 implementation 結案' "$HOME/Desktop/projects/.claude/hooks/friction-review-state.test.sh"
assert_grep "狀態轉換 fixture 保留 optional metadata" 'optional metadata 搬遷時完整保留' "$HOME/Desktop/projects/.claude/hooks/friction-review-state.test.sh"
assert_grep "狀態 helper 驗期限" 'lock-expired' "$HOME/Desktop/projects/.claude/hooks/friction-review-state.py"
assert_grep "command 使用共用狀態 helper" 'friction-review-state\.py (inspect|validate)' "$COMMAND"
assert_grep "結案 SOP 使用 archive helper" 'trial-archive-resources\.py <trial-slug>' "$ACTIVE"
assert_not_grep "結案 SOP 不直接搬 trial 資源" '整個 `mv`|mv ~/\.claude/trials' "$ACTIVE"
assert_grep "archive helper 驗 trial slug" 'invalid-trial-slug' "$ARCHIVER"
assert_grep "archive helper 驗搬遷結果" 'archive-verification-failed' "$ARCHIVER"

mkdir -p "$FIX/home/.claude/skills/example" "$FIX/home/.claude/friction" "$FIX/home/Desktop/projects/.claude/trials"
printf '# fixture\n\n## 待折\n\n- a\n- b\n- c\n\n## 已折／已否決\n' > "$FIX/home/.claude/skills/example/friction-log.md"
printf '# Active Trials\n' > "$FIX/home/Desktop/projects/.claude/trials/active.md"
OUTPUT=$(printf '{"session_id":"%s","cwd":"%s/Desktop/projects"}' "$SESSION" "$FIX/home" | HOME="$FIX/home" FRICTION_SCAN_HOME="$FIX/home" bash "$HOOK")
if printf '%s' "$OUTPUT" | grep -q '跑 /trial-review 處理'; then
  printf 'PASS: hook 導向 trial-review 消費入口\n'
  PASS=$((PASS + 1))
else
  printf 'FAIL: hook 導向 trial-review 消費入口\n'
  FAIL=$((FAIL + 1))
fi

assert_grep "Step 3 R4 拆成 session 級 R4a" 'R4a【' "$COMMAND"
assert_grep "Step 3 R4 拆成檔案級 R4b" 'R4b【' "$COMMAND"
assert_grep "R4b 檔案級違規不屬本 session 認領範圍則回報不代修" 'R4b.*不代修' "$COMMAND"
assert_grep "Step 1 來龍去脈要求重驗 entry 環境事實" '環境事實.*預設重驗' "$COMMAND"
assert_grep "缺能力推薦前枚舉既有設定面" '機制缺少.*profile.*config.*allowlist.*枚舉' "$COMMAND"
assert_grep "外部工具價值判斷先讀第一手" '外部.*工具.*價值判斷.*--help.*官方 README.*子命令.*entry.*功能描述' "$COMMAND"
assert_grep "active.md 檔頭要求 entry 環境事實當場驗" '環境事實.*當場驗' "$ACTIVE"
assert_grep "command 讀取 active index" 'started.*status.*detail' "$COMMAND"
assert_grep "command 明報 detail 缺失" 'detail-missing' "$COMMAND"
assert_grep "active.md 定義固定索引欄位" 'started.*status.*detail' "$ACTIVE"

mkdir -p "$FIX/home/Desktop/projects/.claude/trials/active"
printf '%s\n' '# Active Trials' \
  '## legacy-trial (2000-01-02)' \
  '- legacy body remains readable' \
  '' \
  '## partial-index (2000-01-03)' \
  '- started: 2026-08-22' \
  '- status: active' \
  '' \
  '## indexed-trial (2000-01-01 review date)' \
  '- started: 2026-08-20' \
  '- status: active' \
  '- detail: `active/indexed-trial-2026-08-20.md`' \
  '' \
  '## missing-detail (2000-01-01)' \
  '- started: 2026-08-21' \
  '- status: active' \
  '- detail: `active/missing-detail-2026-08-21.md`' \
  '' \
  '## mismatch-detail (2000-01-01)' \
  '- started: 2026-08-21' \
  '- status: active' \
  '- detail: `active/mismatch-detail-2026-08-21.md`' \
  '' \
  '## trial-a (2000-01-01)' \
  '- started: 2026-08-21' \
  '- status: active' \
  '- detail: `active/trial-b-2026-08-21.md`' \
  '' \
  '## wrong-date (2000-01-01)' \
  '- started: 2026-08-21' \
  '- status: active' \
  '- detail: `active/wrong-date-2099-01-01.md`' \
  '' \
  '## date-only (2000-01-01)' \
  '- started: 2026-08-23' \
  '- status: active' \
  '- detail: `active/date-only-2026-08-22.md`' \
  '' \
  '## wrong-slug (2000-01-01)' \
  '- started: 2026-08-21' \
  '- status: active' \
  '- detail: `active/not-wrong-slug-2026-08-21.md`' \
  '' \
  '## duplicate [run-2] (2000-01-01)' \
  '- started: 2026-08-21' \
  '- status: active' \
  '- detail: `active/duplicate-2-2026-08-21-2.md`' \
  '' \
  '## duplicate-tail (2000-01-01)' \
  '- started: 2026-08-21' \
  '- status: active' \
  '- detail: `active/duplicate-tail-2026-08-21-2.md`' \
  > "$FIX/home/Desktop/projects/.claude/trials/active.md"
printf '%s\n' 'detail-key: active/indexed-trial-2026-08-20.md' 'detail-title: indexed-trial' > "$FIX/home/Desktop/projects/.claude/trials/active/indexed-trial-2026-08-20.md"
printf '%s\n' 'detail-key: active/other-detail-2026-08-21.md' > "$FIX/home/Desktop/projects/.claude/trials/active/mismatch-detail-2026-08-21.md"
printf '%s\n' 'detail-key: active/trial-b-2026-08-21.md' 'detail-title: trial-b' > "$FIX/home/Desktop/projects/.claude/trials/active/trial-b-2026-08-21.md"
printf '%s\n' 'detail-key: active/wrong-date-2099-01-01.md' 'detail-title: wrong-date' > "$FIX/home/Desktop/projects/.claude/trials/active/wrong-date-2099-01-01.md"
printf '%s\n' 'detail-key: active/date-only-2026-08-22.md' 'detail-title: date-only' > "$FIX/home/Desktop/projects/.claude/trials/active/date-only-2026-08-22.md"
printf '%s\n' 'detail-key: active/not-wrong-slug-2026-08-21.md' 'detail-title: wrong-slug' > "$FIX/home/Desktop/projects/.claude/trials/active/not-wrong-slug-2026-08-21.md"
printf '%s\n' 'detail-key: active/duplicate-2-2026-08-21-2.md' 'detail-title: duplicate [run-2]' > "$FIX/home/Desktop/projects/.claude/trials/active/duplicate-2-2026-08-21-2.md"
printf '%s\n' 'detail-key: active/duplicate-tail-2026-08-21-2.md' 'detail-title: duplicate-tail' > "$FIX/home/Desktop/projects/.claude/trials/active/duplicate-tail-2026-08-21-2.md"
INDEX_OUTPUT=$(printf '{"session_id":"%s-index","cwd":"%s/Desktop/projects"}' "$SESSION" "$FIX/home" | HOME="$FIX/home" FRICTION_SCAN_HOME="$FIX/home" bash "$HOOK")
INDEX_MESSAGE=$(printf '%s' "$INDEX_OUTPUT" | python3 -c 'import json, sys; print(json.load(sys.stdin)["systemMessage"])')
if printf '%s' "$INDEX_MESSAGE" | grep -q 'legacy-trial' && ! printf '%s' "$INDEX_MESSAGE" | grep -q 'legacy-trial.*detail-missing'; then
  printf 'PASS: legacy H2 在未遷移時仍列入 review\n'
  PASS=$((PASS + 1))
else
  printf 'FAIL: legacy H2 被誤判成缺 detail\n'
  FAIL=$((FAIL + 1))
fi
if printf '%s' "$INDEX_MESSAGE" | grep -q 'partial-index.*detail-missing'; then
  printf 'PASS: 缺 detail 欄位明確回報\n'
  PASS=$((PASS + 1))
else
  printf 'FAIL: 缺 detail 欄位未回報\n'
  FAIL=$((FAIL + 1))
fi
if printf '%s' "$INDEX_MESSAGE" | grep -q 'mismatch-detail.*detail-mismatch'; then
  printf 'PASS: detail 身分不符明確回報\n'
  PASS=$((PASS + 1))
else
  printf 'FAIL: detail 身分不符未回報\n'
  FAIL=$((FAIL + 1))
fi
if printf '%s' "$INDEX_MESSAGE" | grep -q 'trial-a.*detail-mismatch'; then
  printf 'PASS: foreign detail pointer 明確回報\n'
  PASS=$((PASS + 1))
else
  printf 'FAIL: foreign detail pointer 未回報\n'
  FAIL=$((FAIL + 1))
fi
if printf '%s' "$INDEX_MESSAGE" | grep -q 'indexed-trial'; then
  printf 'PASS: H2 尾綴與索引欄位仍列入 review\n'
  PASS=$((PASS + 1))
else
  printf 'FAIL: H2 尾綴與索引欄位未列入 review\n'
  FAIL=$((FAIL + 1))
fi
if printf '%s' "$INDEX_MESSAGE" | grep -q 'detail 缺失'; then
  printf 'PASS: 長段檔缺失明確回報\n'
  PASS=$((PASS + 1))
else
  printf 'FAIL: 長段檔缺失未回報\n'
  FAIL=$((FAIL + 1))
fi
if printf '%s' "$INDEX_MESSAGE" | grep -q 'wrong-date.*detail-mismatch'; then
  printf 'PASS: detail basename 日期錯誤明確回報\n'
  PASS=$((PASS + 1))
else
  printf 'FAIL: detail basename 日期錯誤未回報\n'
  FAIL=$((FAIL + 1))
fi
if printf '%s' "$INDEX_MESSAGE" | grep -q 'date-only.*detail-mismatch'; then
  printf 'PASS: date-only pointer 的 started 日期錯誤明確回報\n'
  PASS=$((PASS + 1))
else
  printf 'FAIL: date-only pointer 的 started 日期錯誤未回報\n'
  FAIL=$((FAIL + 1))
fi
if printf '%s' "$INDEX_MESSAGE" | grep -q 'wrong-slug.*detail-mismatch'; then
  printf 'PASS: detail basename slug 錯誤明確回報\n'
  PASS=$((PASS + 1))
else
  printf 'FAIL: detail basename slug 錯誤未回報\n'
  FAIL=$((FAIL + 1))
fi
if printf '%s' "$INDEX_MESSAGE" | grep -q 'duplicate \[run-2\].*detail-mismatch'; then
  printf 'FAIL: 正確 run-N detail 被誤判\n'
  FAIL=$((FAIL + 1))
else
  printf 'PASS: 正確 run-N detail 通過 canonical 核對\n'
  PASS=$((PASS + 1))
fi
if printf '%s' "$INDEX_MESSAGE" | grep -q 'duplicate-tail.*detail-mismatch'; then
  printf 'FAIL: 合法 collision suffix detail 被誤判\n'
  FAIL=$((FAIL + 1))
else
  printf 'PASS: 合法 collision suffix detail 通過 canonical 核對\n'
  PASS=$((PASS + 1))
fi

# sunset gate 三項：受測對象是 ~/.claude/hooks/ 下的 live hook。兩支已於 2026-09-07 commit 06e43d6
# 退役搬進 ~/.claude/archive/proj-harness-ledger-hooks-retired-2026-09-07/、settings.json 0 處掛載。
# 缺檔時整段 SKIP 而非 FAIL——原本 fixture 建置會在 read_text 就 crash，讓前兩項無條件 FAIL、
# 第三項「移除 H2 後保持靜默」因空輸出假綠。刻意不改指向 archive 副本：那會變成驗一個不會被執行的檔案。
if [ -f "$SUNSET_NUDGE_SRC" ] && [ -f "$SUNSET_AUDIT_SRC" ]; then
GATE_ACTIVE="$FIX/home/Desktop/projects/.claude/trials/active.md"
printf '%s\n' '# Active Trials' '## proj harness 實跑回饋收斂 (2099-01-05)' '- started: 2026-08-23' '- status: active' '- detail: `active/proj-harness-2026-08-23.md`' > "$GATE_ACTIVE"
mkdir -p "$FIX/home/Desktop/work/oldco-shop" "$FIX/home/.claude/logs"
git init -q "$FIX/home/Desktop/work/oldco-shop"
python3 - "$FIX/home" "$FIX/nudge.sh" "$FIX/audit.sh" "$SUNSET_NUDGE_SRC" "$SUNSET_AUDIT_SRC" <<'PY'
from pathlib import Path
import sys
home, nudge, audit, nudge_src, audit_src = map(Path, sys.argv[1:])
source = nudge_src.read_text()
source = source.replace('~/Desktop/projects/.claude/trials/active.md', str(home / 'Desktop/projects/.claude/trials/active.md'))
nudge.write_text(source)
nudge.chmod(0o755)
source = audit_src.read_text()
source = source.replace('~/Desktop/projects/.claude/trials/active.md', str(home / 'Desktop/projects/.claude/trials/active.md'))
audit.write_text(source)
audit.chmod(0o755)
PY
GATE_NUDGE=$(cd "$FIX/home/Desktop/work/oldco-shop" && CC_VENDOR= HOME="$FIX/home" bash "$FIX/nudge.sh")
if printf '%s' "$GATE_NUDGE" | grep -q 'Harness 實跑回饋 trial 進行中'; then
  printf 'PASS: sunset gate 以新格式 H2 判在案
'
  PASS=$((PASS + 1))
else
  printf 'FAIL: sunset gate 未判新格式 H2 在案
'
  FAIL=$((FAIL + 1))
fi
TRANSCRIPT="$FIX/transcript.jsonl"
printf '%s\n' '{"cwd":"'$FIX'/home/Desktop/work/oldco-shop","message":{"role":"user","content":"run"}}' '{"message":{"role":"assistant","content":"Harness 摩擦 ledger 本次新增 0 條"}}' > "$TRANSCRIPT"
printf '{"session_id":"gate-session","transcript_path":"%s","stop_hook_active":false}' "$TRANSCRIPT" | CC_VENDOR= HOME="$FIX/home" bash "$FIX/audit.sh"
if grep -q '"ledger_reported": true' "$FIX/home/.claude/logs/proj-harness-ledger-audit.jsonl"; then
  printf 'PASS: sunset audit gate 以新格式 H2 判在案
'
  PASS=$((PASS + 1))
else
  printf 'FAIL: sunset audit gate 未判新格式 H2 在案
'
  FAIL=$((FAIL + 1))
fi
printf '%s\n' '# Active Trials' > "$GATE_ACTIVE"
if [ -z "$(cd "$FIX/home/Desktop/work/oldco-shop" && CC_VENDOR= HOME="$FIX/home" bash "$FIX/nudge.sh")" ]; then
  printf 'PASS: sunset gate 移除 H2 後保持靜默
'
  PASS=$((PASS + 1))
else
  printf 'FAIL: sunset gate 移除 H2 後仍輸出
'
  FAIL=$((FAIL + 1))
fi
else
  printf 'SKIP: sunset gate 三項（判在案 / audit 判在案 / 移除 H2 後靜默）——受測 hook 已退役不在 %s\n' "$HOME/.claude/hooks/"
  SKIP=$((SKIP + 3))
fi

printf '%s\n' '----'
printf 'PASS=%s FAIL=%s SKIP=%s\n' "$PASS" "$FAIL" "$SKIP"
[ "$FAIL" -eq 0 ]
