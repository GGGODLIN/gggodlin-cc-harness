# 接線地圖（2026-10-15 起：Magpie）

## 層次

```
消費端（CC session／harbor 容器／腳本）
    ↓  127.0.0.1:8317（relay-switch，依 ~/.magpie-machine/switch-mode 轉送）
Magpie gateway 127.0.0.1:18417（provider 與群組在 ~/.magpie-machine/home/.config/magpie/）
    ↓
vendor endpoint／帳號池／本機 engine
```

- `switch-mode` 只認 `magpie`／`legacy`；部署時寫 `upgrade-maintenance`，期間所有呼叫方收 503。exam2 這類長跑中途撞到，記成基建失敗重考，不算模型失敗。
- CPA（`~/.cli-proxy-api`，`:18318`）與一般 LiteLLM（`:8000`）已停，只留作回退材料。
- harbor 容器內用 `http://host.docker.internal:8317`。

🔌 接線點：跨模型後端 — 見 WIRING.md
