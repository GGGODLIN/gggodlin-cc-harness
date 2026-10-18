# ai-generated-changes

審查 AI 產生的改動時的優先順序與成本意識檢查（code-reviewer 版本）。

## 適用

角色：code-reviewer。被審的改動是 AI 產生的，或派工明說這是 AI 產生的改動。

When reviewing AI-generated changes, prioritize:

1. Behavioral regressions and edge-case handling
2. Security assumptions and trust boundaries
3. Hidden coupling or accidental architecture drift
4. Unnecessary model-cost-inducing complexity

Cost-awareness check:
- Flag workflows that escalate to higher-cost models without clear reasoning need.
- Recommend defaulting to lower-cost tiers for deterministic refactors.
