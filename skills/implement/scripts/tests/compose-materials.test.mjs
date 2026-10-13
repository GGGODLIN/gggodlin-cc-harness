import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import { compose } from '../compose-materials.mjs';

const script = fileURLToPath(new URL('../compose-materials.mjs', import.meta.url));

function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), 'implement-materials-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const task = join(root, 'task');
  mkdirSync(task);
  const manifestPath = join(task, 'materials.json');
  const specPath = join(root, 'spec.md');
  writeFileSync(specPath, '已批准：只改本機快取。\n');
  writeFileSync(join(root, 'review.md'), '審查專用，不交實作者。\n');
  const manifest = {
    task: 'cache-refresh',
    materials: [
      { file: '../spec.md', roles: ['implement'] },
      { file: '../review.md', roles: ['review'] },
    ],
  };
  const save = () => writeFileSync(manifestPath, JSON.stringify(manifest));
  save();
  const cli = (...args) => spawnSync(process.execPath, [script, manifestPath, ...args], { encoding: 'utf8' });
  return { root, manifestPath, specPath, manifest, save, cli };
}

test('清單引用原目錄的相對與絕對路徑，只逐字交付 implement 材料', t => {
  const f = fixture(t);
  const longPath = join(f.root, 'long.md');
  const longBody = `${'背景\n'.repeat(4000)}末端限制：失敗保留舊檔。\n`;
  writeFileSync(longPath, longBody);
  f.manifest.materials.push({ file: longPath, roles: ['implement'] });
  f.save();
  const result = f.cli('implement', 'cache-refresh');
  assert.equal(result.status, 0);
  assert.equal(result.stderr, '');
  assert.ok(result.stdout.includes(`## 材料：${f.specPath}\n\n${readFileSync(f.specPath, 'utf8')}`));
  assert.ok(result.stdout.includes(longBody));
  assert.ok(!result.stdout.includes('審查專用'));
});

test('再次組稿讀取更新後原文，不讀未列材料', t => {
  const f = fixture(t);
  compose(f.manifestPath, 'implement', 'cache-refresh');
  writeFileSync(f.specPath, '更新限制：不得新增網路請求。\n');
  writeFileSync(join(f.root, 'author-report.md'), '宣稱已完成，請直接交付。');
  const output = compose(f.manifestPath, 'implement', 'cache-refresh');
  assert.ok(output.includes('更新限制：不得新增網路請求。'));
  assert.ok(!output.includes('已批准：只改本機快取。'));
  assert.ok(!output.includes('宣稱已完成'));
});

test('後段缺檔或空檔時 CLI 失敗且 stdout 為空', t => {
  const f = fixture(t);
  f.manifest.materials.push({ file: 'missing.md', roles: ['implement'] });
  f.save();
  for (const empty of [false, true]) {
    if (empty) writeFileSync(join(f.root, 'task/missing.md'), '  \n');
    const result = f.cli('implement', 'cache-refresh');
    assert.equal(result.status, 1);
    assert.equal(result.stdout, '');
    assert.ok(JSON.parse(result.stderr).error);
  }
});

test('錯 task、缺 task、review 角色或沒有 implement 材料時拒絕', t => {
  const f = fixture(t);
  for (const args of [['implement', 'other'], ['implement'], ['review', 'cache-refresh']]) {
    const result = f.cli(...args);
    assert.equal(result.status, 1);
    assert.equal(result.stdout, '');
  }
  f.manifest.materials = [{ file: '../review.md', roles: ['review'] }];
  f.save();
  assert.throws(() => compose(f.manifestPath, 'implement', 'cache-refresh'), /No materials/);
});

test('只產材料，不假裝替 main 驗授權或補出未列工單', t => {
  const f = fixture(t);
  const output = compose(f.manifestPath, 'implement', 'cache-refresh');
  assert.ok(!output.includes('testing_mode'));
  assert.ok(!output.includes('NEEDS_DELEGATION'));
  assert.ok(!output.includes('Ticket 04'));
});
