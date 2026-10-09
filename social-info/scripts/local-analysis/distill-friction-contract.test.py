import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'scripts/local-analysis/distill-weekly.sh'


class DistillContract(unittest.TestCase):
  def test_friction_observations_have_one_governance_exit(self):
    text = SOURCE.read_text()
    self.assertIn('根因、治理方案與人類拍板集中於既有 `/trial-review`', text)
    self.assertIn('不另建 H/M/L 或 pending-actions 的同一摩擦待辦', text)
    self.assertIn('一次性已解問題只留本報告', text)
    self.assertIn('模型觀察標 `agent-observation`，疑似加 `speculation`', text)
    for obsolete in ['漂移發現 = 修改提案', '候選 = 修正提案訊號', '修改提案指向的資產']:
      self.assertNotIn(obsolete, text)

  def test_workflow_discovery_and_success_evidence_steps_are_preserved(self):
    original = subprocess.check_output(['git', '-C', str(ROOT), 'show', 'HEAD:scripts/local-analysis/distill-weekly.sh'], text=True)
    current = SOURCE.read_text()
    section_a = re.compile(r'## Step 1.*?(?=## Step 6 —)', re.S)
    self.assertEqual(section_a.search(current).group(), section_a.search(original).group())
    section_d = re.compile(r'1\. 用 Step 1 回報.*?(?=\n完成後接 Step 7。)', re.S)
    self.assertEqual(section_d.search(current).group(), section_d.search(original).group())


if __name__ == '__main__':
  unittest.main()
