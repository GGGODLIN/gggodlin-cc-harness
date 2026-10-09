---
topic: example-config-precedence
last_updated: 2026-02-03
sources:
  - session-0000aaaa
  - https://example.com/demo-cli/docs/config
confidence: medium
lifecycle: reviewed
volatility: low
---

> mock 範例：wiki 條目的格式照真實 schema 寫，內容是虛構工具 demo-cli 的設定優先序，不是真實研究結論。實際使用時條目放在 `~/.claude/wiki/<topic>.md`。

# 範例：demo-cli 設定優先序

## TL;DR
demo-cli 依「命令列旗標 → 專案設定 → 全域設定 → 內建預設」決定設定值；專案層會整段覆蓋全域層的同名區塊。

## 核心概念
- 旗標永遠最優先，適合一次性覆寫。
- 專案設定放在 repo 根目錄，跟著版控走；全域設定只放個人偏好。
- 同名區塊不合併：專案層寫了 `[format]`，全域層的 `[format]` 整段失效。

## 已知限制 / 坑
- 設定檔裡的 `~` 不展開（見 memory 範例 reference_example_cli_config_traps）。
- `--print-effective` 只顯示最終值，不顯示來自哪一層；要查來源得逐層關掉比對。

## 相關
[[example-tool-adoption]]

## Changelog
- 2026-01-20: 首版（source: session-0000aaaa）
- 2026-02-03: 補上同名區塊不合併的坑（source: session-0000bbbb）
