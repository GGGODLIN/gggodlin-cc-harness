# 三層接線地圖

## 層次

```
CLIProxyAPI relay (:8317)
    ↓  provider 指向 litellm
litellm gateway (:8000)
    ↓  api_base 指向 adapter 或直接指向 vendor
adapter / vendor endpoint
    ↓
真正的模型
```

不是每顆模型都要走滿三層。判定方式是**誰要消費它**：

- 只給腳本或 hook 用（單次來回）→ 進 litellm 就夠
- 要給 CC、pi、其他 agent harness 用，或要排進 `free` chain → 必須進到 relay

🔌 接線點：跨模型後端 — 見 WIRING.md

## 漏層的症狀

漏層不會報錯，只會「某個消費端看不到這顆模型」。所以完成條件是三層各自 curl 過、都列得出來，而不是改完設定檔就宣告接好。

2026-09-17 接 MiMo 時就漏了：`mimo-x-flash` 進了 adapter 與 litellm，沒進 relay，而 litellm 那層測起來完全正常。（那顆後來因與 pro 共用額度而整個退場，這裡只留漏層的形狀當案例。）

## 重啟沒生效的判定

改了設定檔但 probe 還是舊的，先比對**服務啟動時間**與**設定檔 mtime**：

```bash
ps -o pid,lstart -p <pid>
stat -f "%Sm %N" -t "%Y-%m-%d %H:%M:%S" <config>
```

啟動時間早於 mtime，就是沒重啟成功，不是設定寫錯。

🔌 接線點：跨模型後端 — 見 WIRING.md
