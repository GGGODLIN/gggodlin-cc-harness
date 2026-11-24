import sys
import unittest
from pathlib import Path

# Hooks and the rest of this suite run under `python3 -I`, which drops the script directory from sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from decision import decide, gpt_pro_context_mode


STOP_CHOICES = (
  {"has_recommendation": True, "has_default": False},
  {"has_recommendation": False, "has_default": True},
  {"has_recommendation": False, "has_default": False},
)
LOCAL_ACTIONS = (
  "local-decision", "herdr-worker", "native-fable", "locked-file-commit", "codex-astra",
)
HIGH_COST_ACTIONS = (
  "git-force-push", "git-hard-reset", "git-restore-worktree", "git-delete-branch",
  "git-rebase", "git-amend-pushed", "git-delete-repo", "git-merge-pr", "git-shared-main-push",
  "publish-outward", "upstream-pr-publish", "upstream-public-fork-push", "upstream-pr-comment",
  "company-repo-push", "company-pr-create", "send-message", "acme-db-write", "third-party-fable",
)
PERSONAL = {
  "status": "ok", "workspaceId": "test-personal", "workspaceName": "Personal",
  "planType": "pro", "devspace": "available",
}


class ApprovalDecisionTests(unittest.TestCase):
  def evaluate(self, action, *, enabled=True, choice=STOP_CHOICES[0], preflight=None):
    return decide(stop_kind="authorization", action=action, enabled=enabled, preflight=preflight, **choice)

  def test_disabled_requires_human(self):
    cases = [(action, None) for action in (*LOCAL_ACTIONS, *HIGH_COST_ACTIONS, "unrecognized")]
    cases.extend((("web-gpt-pro", PERSONAL), ("web-gpt-pro", None)))
    for action, preflight in cases:
      for choice in STOP_CHOICES:
        with self.subTest(action=action, preflight=preflight, choice=choice):
          self.assertEqual(self.evaluate(action, enabled=False, choice=choice, preflight=preflight), "require-human")

  def test_recommendation_or_default_allows_auto(self):
    for action in (*LOCAL_ACTIONS, "unrecognized", "custom-stop-action"):
      for choice in STOP_CHOICES[:2]:
        with self.subTest(action=action, choice=choice):
          self.assertEqual(self.evaluate(action, choice=choice), "allow-auto")

  def test_both_choices_can_be_present(self):
    self.assertEqual(self.evaluate("local-decision", choice={"has_recommendation": True, "has_default": True}),
                     "allow-auto")

  def test_malformed_choice_cannot_be_overridden_by_a_valid_choice(self):
    for invalid in (0, 1, "true", None, [], {"provided": False}):
      for choice in ({"has_recommendation": invalid, "has_default": True},
                     {"has_recommendation": True, "has_default": invalid}):
        with self.subTest(choice=choice):
          self.assertEqual(self.evaluate("local-decision", choice=choice), "require-human")

  def test_blank_or_non_string_stop_kind_requires_human(self):
    for stop_kind in ("", " \t　", None, False, 1, [], {}):
      with self.subTest(stop_kind=stop_kind):
        self.assertEqual(decide(stop_kind=stop_kind, action="local-decision", enabled=True, **STOP_CHOICES[0]),
                         "require-human")

  def test_no_choice_or_blank_action_requires_human(self):
    cases = [(action, STOP_CHOICES[2], None) for action in (*LOCAL_ACTIONS, "unrecognized")]
    cases.append(("web-gpt-pro", STOP_CHOICES[2], PERSONAL))
    cases.extend((action, choice, None) for action in ("", "   ", None, []) for choice in STOP_CHOICES)
    for action, choice, preflight in cases:
      with self.subTest(action=action, choice=choice):
        self.assertEqual(self.evaluate(action, choice=choice, preflight=preflight), "require-human")

  def test_high_cost_actions_are_downweighted(self):
    for action in HIGH_COST_ACTIONS:
      for choice in STOP_CHOICES:
        with self.subTest(action=action, choice=choice):
          self.assertEqual(self.evaluate(action, choice=choice), "downweight")

  def test_gpt_pro_workspace_and_context_mode(self):
    cases = (
      ("personal with DevSpace", PERSONAL, "allow-auto", "snapshot"),
      ("personal without DevSpace", {**PERSONAL, "devspace": "unavailable"}, "allow-auto", "materials"),
      ("personal with unknown DevSpace", {**PERSONAL, "devspace": "unknown"}, "allow-auto", "materials"),
      ("personal Pro", {**PERSONAL, "workspaceName": "Other Personal"}, "allow-auto", "snapshot"),
      ("unverified Plus", {**PERSONAL, "planType": "plus"}, "downweight", None),
      ("company", {**PERSONAL, "workspaceId": "test-company", "workspaceName": "acme, Inc.",
                   "planType": "self_serve_business_prolite"}, "downweight", None),
      ("other company", {**PERSONAL, "workspaceId": "test-company", "workspaceName": "Other Company",
                         "planType": "self_serve_business_prolite"}, "downweight", None),
      *((plan, {**PERSONAL, "planType": plan}, "downweight", None)
        for plan in ("team_pro", "enterprise_pro", "edu_plus", "unlisted")),
      ("unknown workspace", {**PERSONAL, "workspaceName": "unknown"}, "downweight", None),
    )
    for label, preflight, decision, context_mode in cases:
      for choice in STOP_CHOICES[:2]:
        with self.subTest(workspace=label, choice=choice):
          self.assertEqual(self.evaluate("web-gpt-pro", choice=choice, preflight=preflight), decision)
          self.assertEqual(gpt_pro_context_mode(preflight), context_mode)

  def test_missing_null_timed_out_or_failed_preflight_is_downweighted(self):
    cases = [
      ("absent", None), ("non-object", []),
      ("timeout", {**PERSONAL, "status": "timeout"}),
      ("failed", {**PERSONAL, "status": "blocked"}),
      ("empty ID", {**PERSONAL, "workspaceId": " "}),
      ("malformed DevSpace status", {**PERSONAL, "devspace": []}),
    ]
    for field in ("status", "workspaceId", "workspaceName", "planType", "devspace"):
      cases.append((f"missing {field}", {key: value for key, value in PERSONAL.items() if key != field}))
      cases.append((f"null {field}", {**PERSONAL, field: None}))
    for label, preflight in cases:
      with self.subTest(preflight=label):
        self.assertEqual(self.evaluate("web-gpt-pro", preflight=preflight), "downweight")
        self.assertIsNone(gpt_pro_context_mode(preflight))


if __name__ == "__main__":
  unittest.main(verbosity=2)
