#!/usr/bin/env python3
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REFERENCE = 'references/verification-recipes-and-probes.md'
POINTER = f'~/.claude/{REFERENCE}'


def section(text, start, end=None):
  value = text[text.index(start):]
  return value[:value.index(end)] if end else value


class VerificationRecipeGrafts(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.reference = (ROOT / REFERENCE).read_text()
    cls.e2e = (ROOT / 'skills/e2e-explore-then-batch/SKILL.md').read_text()
    cls.implement = (ROOT / 'skills/implement/SKILL.md').read_text()
    cls.review = (ROOT / 'commands/pr-review.md').read_text()

  def test_e2e_both_exit_paths_read_the_shared_recipe(self):
    for start, end in (
      ('## Step 2 —', '## Step 2.5 —'),
      ('## Step 3 —', '## 踩過的坑'),
    ):
      with self.subTest(start=start):
        body = section(self.e2e, start, end)
        self.assertIn(POINTER, body)
        self.assertIn('如果本', body)
        self.assertIn('清理', body)
        self.assertIn('驗證配方維護', body)

  def test_implement_closeout_keeps_both_conditional_branches(self):
    body = section(self.implement, '## 3. Close out')
    recipe = section(body, '3. ', '4. Review the work')
    review = section(body, '4. Review the work', '5. Receive the review')
    self.assertIn(POINTER, recipe)
    self.assertIn('已有可重用驗證配方', recipe)
    self.assertIn('尚未證明的行為事實', review)
    self.assertIn(POINTER, review)
    self.assertIn('不另開 review 輪', review)

  def test_pr_review_passes_text_to_existing_verifiers(self):
    body = section(self.review, '## Step 4: Cross-Axis Verification Pass', '### Step 4.1:')
    for expected in (POINTER, '4.1／4.2', '該段原文附入同一份核驗 prompt',
                     '沿用 selected findings', '不加 reviewer 或新一輪', 'INCONCLUSIVE'):
      with self.subTest(expected=expected):
        self.assertIn(expected, body)

  def test_recipe_reuses_assets_and_preserves_evidence(self):
    body = section(self.reference, '## 驗證配方維護', '## 安全假設 probe')
    for expected in ('不建立空索引', '已有正本就引用', '未實跑的入口標未驗證',
                     '不為此另造 doctor', '清理後實際確認仍可讀', '不重跑'):
      with self.subTest(expected=expected):
        self.assertIn(expected, body)

  def test_comparator_check_is_conditional_and_preserves_approved_inputs(self):
    body = section(self.reference, '## 驗證配方維護', '## 安全假設 probe')
    for expected in ('新增、改動或有具體疑點', '判 PASS 前', '隔離副本',
                     '同一比較入口、遮蔽與容差設定', '確認有實際比較且回報差異',
                     '不改產品、原始預期或批准設定', '這條驗證未成立',
                     '有效同題證據可沿用', '再接清理'):
      with self.subTest(expected=expected):
        self.assertIn(expected, body)

  def test_regression_path_reads_the_comparator_check_before_pass(self):
    body = (ROOT / 'skills/implement/references/regression-closeout.md').read_text()
    check = section(body, '5. ', '6. ')
    self.assertIn('新增、改動或有具體疑點', check)
    self.assertIn('判 PASS 前讀', check)
    self.assertIn(f'/{REFERENCE}', check)
    self.assertIn('不新增固定 mutation 關卡', check)

  def test_probe_preserves_authority_and_reuses_evidence(self):
    body = section(self.reference, '## 安全假設 probe', '## trial 觀察')
    for expected in ('尚未證明', '執行上限', '釘定依賴版本', '真實模組',
                     '不要 mock', '不自行擴權', '不自動授權修 code', '證據沒變就沿用'):
      with self.subTest(expected=expected):
        self.assertIn(expected, body)

  def test_observation_uses_existing_artifacts_without_empty_rows(self):
    body = section(self.reference, '## trial 觀察')
    for expected in ('既有 trajectory', 'Verification Log', '沒有增量',
                     '未命中不加空欄', '不另開日誌', '不把合成演練算自然使用'):
      with self.subTest(expected=expected):
        self.assertIn(expected, body)


if __name__ == '__main__':
  unittest.main()
