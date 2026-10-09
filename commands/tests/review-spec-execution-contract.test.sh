#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
COMMAND="${REVIEW_SPEC_COMMAND_PATH:-$ROOT/commands/review-spec.md}"
MODEL_ROUTING="${MODEL_ROUTING_PATH:-$ROOT/model-routing.env}"
PASS=0
FAIL=0

assert_grep() {
  local label=$1 pattern=$2
  if grep -qE "$pattern" "$COMMAND"; then
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

assert_not_grep() {
  local label=$1 pattern=$2
  if grep -qE "$pattern" "$COMMAND"; then
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  else
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  fi
}

assert_routing_grep() {
  local label=$1 pattern=$2
  if grep -qE "$pattern" "$MODEL_ROUTING"; then
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

first_match_line() {
  local pattern=$1 line
  while IFS=: read -r line _; do
    printf '%s\n' "$line"
    return 0
  done < <(grep -nF "$pattern" "$COMMAND")
  return 1
}

assert_order() {
  local label=$1 first=$2 second=$3 first_line second_line
  first_line=$(first_match_line "$first" || true)
  second_line=$(first_match_line "$second" || true)
  if [ -n "$first_line" ] && [ -n "$second_line" ] && [ "$first_line" -lt "$second_line" ]; then
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

assert_yagni_grep() {
  local label=$1 pattern=$2
  if awk '/^## YAGNI 軸/{in_yagni=1} /^## 呈現紀律/{in_yagni=0} in_yagni' "$COMMAND" | grep -qE "$pattern"; then
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

assert_t4_grep() {
  local label=$1 pattern=$2
  if awk '/^## Tier 4 /{in_t4=1} /^## 標準 Tier 1–4 共用收斂/{in_t4=0} in_t4' "$COMMAND" | grep -qE "$pattern"; then
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

assert_t4_not_grep() {
  local label=$1 pattern=$2
  if awk '/^## Tier 4 /{in_t4=1} /^## 標準 Tier 1–4 共用收斂/{in_t4=0} in_t4' "$COMMAND" | grep -qF "$pattern"; then
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  else
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  fi
}

assert_yagni_not_grep() {
  local label=$1 pattern=$2
  if awk '/^## YAGNI 軸/{in_yagni=1} /^## 呈現紀律/{in_yagni=0} in_yagni' "$COMMAND" | grep -qF "$pattern"; then
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  else
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  fi
}

assert_grep "command marks this contract test" '本檔在契約測試底下.*review-spec-execution-contract\.test\.sh'
assert_grep "default OpenSpec design path" 'openspec/changes/\*/design\.md'
assert_grep "default OpenSpec proposal path" 'openspec/changes/\*/proposal\.md'
assert_grep "default scratch spec path" '\.scratch/\*/spec\.md'
assert_grep "local OpenSpec tasks path" 'openspec/changes/<change>/tasks\.md'
assert_not_grep "retired workflow paths are absent" 'docs/superpowers|superpowers'
assert_grep "Tier 3 presents model rows and lens columns" '模型／執行路徑為直列，角度為橫欄'
assert_grep "Tier 3 recommendation does not authorize dispatch" '推薦只是建議，不是授權'
assert_grep "Tier 3 binds recommendation to same-round assistant evidence" 'top-level assistant envelope.*review-spec-recommendation:v1 permit_id=<id> seats=<lens:model,...>>'
assert_grep "Tier 3 follow recommendation requires exact seat set" '照推薦.*席位集合完全相同'
assert_grep "Tier 3 supports natural language seat changes" '指定換模型.*同角度加席.*減席.*取消角度.*自然語言'
assert_grep "Tier 3 finalizes explicit model lens seats" 'finalize.*--seats.*lens:model'
assert_grep "Tier 3 finalization binds recommendation event" '.*--recommendation-event.*assistant event UUID'
assert_grep "Tier 3 follow recommendation is explicit" '.*--follow-recommendation'
assert_grep "Tier 3 preserves explicit pair shortcut" '.*--lenses.*雙跑快捷方式'
assert_grep "Tier 3 legacy shortcut still needs user selection" 'top-level user.*明示配對選擇.*legacy shortcut'
assert_grep "Tier 3 legacy shortcut still needs reference Read" 'legacy shortcut.*reference＋完整 Read'
assert_grep "Tier 3 stops unstarted seats after capacity rejection" '容量拒絕.*停止尚未派出的席位'
assert_grep "Tier 4 uses detached rollout polling" 'subshell \+ nohup detach \+ rollout jsonl poll'
assert_t4_grep "Tier 4 Web GPT collects with a plain detail call" 'web-cli chatgpt detail <id> --markdown true -f json'
assert_t4_not_grep "Tier 4 never waits on detail stabilization" 'detail <id> --wait true'
assert_t4_grep "Tier 4 reads the prompt into a variable before dispatch" 'PROMPT=\$\(cat'
assert_t4_grep "Tier 4 verifies the Pro model slug after the run" 'data-message-model-slug'
assert_t4_grep "Tier 4 keeps the background window flag" 'ask "\$PROMPT" --new --window background'
assert_t4_grep "Tier 4 no response leaves seats unselected" 'AFK.*無回應.*不派任何外部席位'
assert_t4_not_grep "Tier 4 does not default to dual dispatch" '預設雙路都跑|AFK.*預設雙路'
assert_not_grep "Tier 4 no longer uses current-conversation read" 'web-cli chatgpt read'
assert_not_grep "Tier 4 no longer forces foreground Codex" 'main session 前景跑|task --fresh.*不加.*--background'
assert_grep "review-spec reads shared model routing" 'model-routing\.env'
assert_grep "review-spec uses strict model routing helper" 'scripts/model-routing\.sh.*GEMINI_FLASH_MODEL'
assert_not_grep "review-spec never sources routing data as shell" 'source .*model-routing\.env'
assert_grep "review-spec uses shared Gemini Flash model" 'agy --model "\$GEMINI_FLASH_MODEL"'
assert_not_grep "hardcoded agy Flash display model is absent" 'agy --model "Gemini [^"]*Flash[^"]*"'
assert_not_grep "hardcoded agy Flash canonical id is absent" 'agy --model "gemini-[^"]*flash[^"]*"'
assert_routing_grep "shared routing pins Gemini 3.8 Flash" '^GEMINI_FLASH_MODEL=gemini-3\.8-flash-high$'
assert_grep "Tier 3 binds vendor Opus and Fable mappings" 'ANTHROPIC_DEFAULT_OPUS_MODEL.*ANTHROPIC_DEFAULT_FABLE_MODEL'
assert_grep "Tier 3 rejects identical vendor role mappings" '兩者必須非空且不同'
assert_not_grep "Tier 3 no longer rejects every vendor session" '非空值直接停止'
assert_grep "Tier 3 menu advertises vendor role mapping" '原生或 distinct vendor mapping'
assert_grep "Tier 3 uses file-backed packet references" 'packet .*--reference'
assert_grep "Tier 3 packet names the selected model" 'packet.*--model <opus\|fable>'
assert_grep "Tier 3 requires full packet Read" '第一個動作必須用 Read 完整讀取.*REVIEW_SPEC_PACKET_PATH'
assert_grep "Tier 3 verifier accepts a single seat" '.*--seat <slug>:<opus\|fable>:<agent-id>'
assert_grep "Tier 3 verifier keeps explicit pair shortcut" '.*--pair <slug>:<opus-agent-id>:<fable-agent-id>'
assert_grep "Tier 3 completion follows selected seats" '單席只驗該席，只有選定配對才要求兩席都完成'
assert_grep "Tier 3 reports incomplete selected seats" '選定席位未完成'
assert_grep "Tier 3 does not count unselected seats" '不得拿舊記錄、單支、偽造 receipt 或未選席位冒充完成'
assert_grep "architecture spec surfaces intent diagram choice" '架構意圖圖.*a\. 生成.*b\. 跳過'
assert_grep "intent nudge keys on boundary changes" 'boundary.*cross-boundary edge'
assert_grep "intent diagram is proposed authored evidence" 'proposed/authored'
assert_grep "intent skip or silence does not block implementation" '選 b 或不回答.*不阻塞'
assert_grep "pre-generation skip invokes neither gate" '0 次 Archify.*0 次 Plannotator'
assert_grep "intent launch requires receipt validation" '只有.*wrapper.*成功.*receipt validation.*才.*plannotator-review\.mjs intent'
assert_order "intent wrapper precedes shared Plannotator adapter" 'archify-safe.mjs intent' 'plannotator-review.mjs intent'
assert_grep "intent adapter launches as one background task" 'Bash\(run_in_background=true\).*plannotator-review\.mjs intent'
assert_grep "intent adapter task binds its source receipt" 'adapterTaskId.*wrapper receipt identity'
assert_grep "background handoff is not an adapter timeout" 'moved to background.*仍在執行.*不是.*adapter timeout'
assert_grep "live intent task is never relaunched" 'adapter task.*live.*不得啟動第二支'
assert_grep "intent waits for harness completion" 'task-notification.*completed.*failed'
assert_grep "intent reads one completed output and receipt" 'Read.*output file.*一次.*唯一.*receipt'
assert_grep "intent does not ask for manual relaunch" '不得要求.*user shell.*重跑'
assert_order "shared adapter launch precedes task completion" 'plannotator-review.mjs intent' 'task-notification'
assert_order "task completion precedes intent acceptance" 'task-notification' 'intent-accepted'
assert_grep "approved intent maps to intent-accepted" 'decision=approved.*transition=intent-accepted'
assert_grep "intent acceptance releases only its downstream path" 'intent-accepted.*review-spec completion.*to-tickets.*implement'
assert_grep "approved notes keep intent acceptance transition" 'approved with notes.*decision=approved.*transition=intent-accepted'
assert_grep "approved notes reach downstream inputs" 'approved with notes.*(persist|持久化).*feedback.*adapter receipt path.*downstream implementation inputs'
assert_grep "annotated maps to classification-required" 'decision=annotated.*transition=classification-required'
assert_grep "annotated feedback is persisted and blocks" 'annotated.*(persist|持久化).*feedback.*BLOCKED'
assert_grep "annotated asks top-level human classification" 'classification-required.*top-level human.*artifact-inaccurate.*architecture-rejected'
assert_grep "agent cannot guess annotated classification" 'agent 不得自行猜測'
assert_grep "artifact-inaccurate reruns the same intent source" 'artifact-inaccurate.*同一份已接受的 spec.*同一個 intent source.*重生.*重跑'
assert_grep "architecture rejection returns to spec revision" 'architecture-rejected.*spec revision.*舊 artifact.*adapter decision.*同時失效'
assert_grep "dismissed and infrastructure failures block" 'dismissed.*timeout.*gate-error.*invalid result.*receipt/artifact drift.*BLOCKED'
assert_grep "missing classification blocks" 'classification.*no answer.*BLOCKED'
assert_grep "wait-what visual integration is retired" '/wait-what.*互動圖.*退役'
assert_grep "Figma and native PlanMode remain unchanged" 'Figma.*native PlanMode.*不變'

assert_not_grep "polarity ledger append no longer mandated (trial closed 2026-07-14)" '每跑完 T3 必 append'
assert_grep "Tier 3 checks remaining permit TTL before dispatch" '剩餘 TTL'
assert_grep "Tier 3 runtime failure report leads with three plain sentences" 'review 有沒有開始／卡在哪一層／現在只決定什麼'
assert_grep "surfacing triages first and batches real decisions into one final round" '最後一輪拍板表'
assert_grep "cross-component tradeoffs show the current call tree before decisions" '跨元件／多分支 trade-off 先畫目前流程.*拍板表前.*call tree'
assert_grep "reversals isolate the sole before-now delta" '之前／現在.*唯一翻案'
assert_grep "side findings stay separate with default recommendations" '旁支發現.*預設建議'
assert_not_grep "surfacing no longer stops per finding for act/ignore" '一次 surface 一條'
assert_grep "yagni surfacing leads with three plain sentences" '這輪在審值不值得做／'
assert_yagni_grep "YAGNI packet uses Write tool" 'packet.*Write tool'
assert_yagni_grep "YAGNI packet uses neutral scratch path" 'review-spec-yagni-packet-<session-id>\.md'
assert_yagni_not_grep "YAGNI packet is no longer written beside spec" 'packet 用 Write tool 寫到 spec 同目錄'
assert_yagni_grep "YAGNI packet forbids shell redirection" '不得用 shell redirect 寫 packet'
assert_yagni_not_grep "YAGNI does not blame unverified command substitution" '$(cat)'
assert_yagni_grep "web Pro seat reads the packet into a variable first" 'PROMPT=\$\(cat'
assert_yagni_grep "web Pro fallback lists connected profiles before dispatch" 'web-cli profile list'
assert_yagni_grep "web Pro fallback identifies every candidate account" 'web-cli --profile .* chatgpt whoami -f json'
assert_yagni_grep "same-account profiles choose the first listed profile" '相同且非空的 `user_id` 時選清單第一個'
assert_yagni_grep "unknown identities cannot auto-select" '身分不明.*不得自動選'
assert_yagni_grep "different identities require a human choice" '身分不同.*使用者選'
assert_yagni_grep "web Pro seat opens a new conversation with the selected profile" 'web-cli --profile .* chatgpt ask "\$PROMPT" --new'
assert_yagni_grep "web Pro seat collects the answer with the same selected profile" 'web-cli --profile .* chatgpt detail <conversationId> --markdown true'
assert_yagni_not_grep "web Pro seat never waits on detail stabilization" 'detail.*--wait true'
assert_yagni_grep "web Pro dispatch keeps the background window flag" 'ask "\$PROMPT" --new --window background'
assert_yagni_grep "web Pro findings outside the packet are disqualified" 'out-of-packet'
assert_yagni_grep "web Pro seat verifies the model slug after the run" 'data-message-model-slug'
assert_yagni_grep "YAGNI prompt forbids external lookup" '禁外查'
assert_yagni_grep "yagni defaults to the single c seat" '預設單席 c'
assert_yagni_not_grep "yagni no longer dispatches the agy Gemini seat" 'agy --model'
assert_grep "seat acceptance validates output shape" '席位驗收.*輸出 shape'
assert_grep "wrong shape gets one focused retry" '不符.*focused retry.*一次'
assert_grep "stalled seat preserves completed results" '兩次 60 秒.*完成席.*單席'
assert_grep "security finding checks known credential exception" 'security finding.*known.*exception.*Context7'
assert_yagni_grep "zero demote requires concrete proof" '0.*demote.*逐條.*具體損失'
assert_yagni_grep "c seat uses batched sentinel contract" 'c 席走 deterministic 分批契約.*sentinel.*60 秒.*invalid'
assert_yagni_grep "c seat asks the model tier before dispatch" '派工前先問模型級別'
assert_yagni_grep "c seat tier menu resolves both actual values" 'fable 級 →.*opus 級 →'
assert_yagni_grep "seat and model are asked as one merged menu" '席位＋模型合併成一題.*只回一個字母'
assert_yagni_grep "Fable permit reads the Fable letters from the menu itself" '代表 fable 的字母'
assert_yagni_grep "to-spec menu f counts as the YAGNI entry" 'review-spec-entry-menu:v1'
assert_yagni_not_grep "the separate seat question is gone" '「派工擇一：YAGNI 席位（單選）— a. 只派 c 席 b. c 席 ＋ web GPT Pro 席'
assert_yagni_grep "c seat flags a free-pool opus mapping" 'free 池'
assert_yagni_grep "c seat records the resolved model in its report" 'resolved_model'
assert_yagni_grep "resolved model is recorded, not an acceptance gate" 'resolved_model.*只作紀錄、不作驗收條件'
assert_yagni_grep "only a silent downgrade from the fable tier invalidates" '選了 fable 級卻跑出別的級別'
assert_yagni_grep "any model inside the free pool counts as a match" 'free.*池內任何一顆都算相符'
assert_yagni_not_grep "c seat no longer hardcodes the fable tier" '派工必帶 `model: "fable"`'
assert_yagni_grep "silent model selection falls back to policy-compliant opus" 'AFK 或無回應走 opus 級'
assert_yagni_grep "Fable menu names the packet path" '<review-spec-yagni-model-menu:v1 packet=<packet 絕對路徑>>'
assert_yagni_grep "Fable selection issues a trusted permit" 'review-spec-yagni-permit.py issue --session'
assert_yagni_grep "each Fable batch gets one permit marker" 'review-spec-yagni-permit.py marker --session.*--batch <stories\|decisions>'
assert_yagni_grep "YAGNI Fable uses the dedicated marker" '<review-spec-yagni:v1'
assert_yagni_grep "generic Fable marker is forbidden on YAGNI permits" 'description \*\*只放\*\*.*不加 generic `<fable-ok>`'
assert_yagni_grep "both accepted batches close the permit" 'review-spec-yagni-permit.py close --session'
assert_yagni_grep "Fable permit completion requires two consumes and close" 'stories／decisions 各一筆 permit consume audit、close 成功'
assert_yagni_grep "native seat starts with real request" '真正 request.*不是.*auth status'
assert_grep "standard review has shared root closeout" '^## 標準 Tier 1–4 共用收斂：root / first_nail'
assert_grep "synthesis follows selected seats" '所有選定席位完成.*synthesize'
assert_grep "polarity only applies to selected pair" '只有兩個對立席位都被選定時才適用'
assert_grep "shared closeout defines load-bearing root" 'root.*唯一承重問題'
assert_grep "shared closeout defines cheapest falsification" 'first_nail.*最便宜.*證偽'
assert_yagni_not_grep "YAGNI section does not invoke first_nail" 'first_nail'
assert_grep "shared closeout explicitly excludes YAGNI axis" 'YAGNI 軸已有分母檢查與最簡版舉證，暫不套本段'
assert_grep "validation integrity explicitly excludes YAGNI axis" 'YAGNI 軸不套本項'
assert_grep "YAGNI retains shared rules zero and four" '貫穿守則（標準 Tier 1–4 全部適用；YAGNI 僅沿用守則 0 與 4）'
assert_grep "no-single-root expands first nails" '無單一承重問題.*第一個驗證.*每個獨立 root 逐行展開'
assert_grep "done criteria handles independent roots" 'root（或「無單一承重問題」時的每個獨立 root）能解釋為何它承重'
assert_grep "validation integrity trigger covers eval family" 'eval.*benchmark.*A/B.*judge.*scorer.*holdout'
assert_grep "validation integrity audits leakage taxonomy" '記答案代替推理.*錯誤對照組.*同源互相認證.*設計者兼裁判'
assert_grep "validation integrity writes clean test requirements" '乾淨測試要求.*寫回 spec'
assert_grep "review-spec leaves ticket creation to to-tickets" 'review-spec.*不直接.*ticket.*to-tickets'
CONVERGENCE_POINTERS=$(grep -cF '完成後接「標準 Tier 1–4 共用收斂」' "$COMMAND")
if [ "$CONVERGENCE_POINTERS" -eq 4 ]; then
  printf 'PASS: all four standard tiers connect shared convergence\n'
  PASS=$((PASS + 1))
else
  printf 'FAIL: all four standard tiers connect shared convergence (got %s)\n' "$CONVERGENCE_POINTERS"
  FAIL=$((FAIL + 1))
fi

assert_grep "every finding carries a fixed-shape disposition line" '^- disposition: <ID> \| <class> \| main=<verdict> \| user=<verdict> \|'
assert_grep "disposition classes match the triage vocabulary" 'misread.*actionable.*tradeoff.*noise'
assert_grep "user verdict vocabulary is fixed" 'accepted.*dismissed.*deferred.*n/a'
assert_grep "findings get stable IDs so dispositions are addressable" 'F1.*F2'
assert_grep "prior dispositions are read back before dispatching reviewers" 'grep -h .\^- disposition:'
assert_grep "read-back happens before the critic dispatch, not after" '派 critic 前.*先讀回'
assert_grep "rubber-stamp tally is computed, not remembered" '連續 2\+ 輪.*0 條 actionable'
assert_grep "zero prior review files is stated rather than assumed clean" '查無前輪'

printf '%s\n' '----'
printf 'PASS=%s FAIL=%s\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
