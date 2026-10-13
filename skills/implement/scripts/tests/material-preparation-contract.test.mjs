import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const skill = readFileSync(new URL('../../SKILL.md', import.meta.url), 'utf8');
const reference = readFileSync(new URL('../../references/material-preparation.md', import.meta.url), 'utf8');
const control = skill.slice(skill.indexOf('Subagent-Driven control loop:'), skill.indexOf('## 3. Close out'));

test('材料分支接在控制迴圈組 prompt 前，範圍檢查先行', () => {
  assert.match(control, /已有材料清單.*後續會再次派工/);
  assert.match(control, /完成上方 Main scope 差額檢查後讀.*material-preparation\.md/);
  assert.ok(control.indexOf('material-preparation.md') < control.indexOf('2. Dispatch'));
  assert.match(control, /完成材料準備後回本步/);
  assert.match(control, /只有一次交付且沒有清單時沿原路/);
});

test('新增接點不取代原 prompt 或擴到審查', () => {
  assert.match(control, /只填材料區.*完整票文、測試模式、權限/);
  assert.match(control, /review-implement 不走此路/);
  assert.match(control, /NEEDS_DELEGATION/);
  assert.match(control, /BLOCKED:/);
  assert.match(reference, /main 另外保留原 skill 的票絕對路徑、完整票文/);
  assert.match(reference, /不更換 Agent／pi 選路或模型/);
});

test('原檔、更新與失敗分支有可觀察的處理', () => {
  assert.match(reference, /原檔不搬、不自動掃描目錄/);
  assert.match(reference, /最新文件不代表內容已批准/);
  assert.match(reference, /重用前核對原文是否變動/);
  assert.match(reference, /compose-materials\.mjs <清單絕對路徑> implement <task-id>/);
  assert.match(reference, /只有 exit 0 才讀輸出/);
  assert.match(reference, /不送該輸出，也不復用上一份輸出/);
  assert.match(reference, /不驗清單語意完整性/);
});

test('觀察沿既有 trial，每任務一行且不灌入合成使用', () => {
  assert.match(reference, /4\. \*\*記實際工夫/);
  assert.match(reference, /派工後、返回 frontier 前讀.*active\.md/);
  assert.match(reference, /context-preparation-offline/);
  assert.match(reference, /首次準備動作.*實際省掉的動作.*維護、同步或補送/);
  assert.match(reference, /不把 authoring 測試算自然使用/);
  assert.match(reference, /零使用.*收益未驗證/);
});
