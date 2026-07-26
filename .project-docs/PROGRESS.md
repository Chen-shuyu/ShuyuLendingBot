# PROGRESS

## 2026-07-26
- 完成：接手專案（原由 GitHub Copilot 協助撰寫），盤點現有 dry-run 雛型與
  `SHUYU_PROJECT_PLAN.md` 規劃書內容；建立 `.project-docs/` 文件結構
  （PLAN／PROGRESS／DECISIONS／TASKS／CHANGELOG／ARCHITECTURE），把規劃書內容分類歸位
- 完成：與使用者確認 4 項待定事項並記錄為決策：部署主線採 Podman 容器化（D007）、
  舊規劃文件歸檔至 `archive/` 不刪除（D008）、LINE 憑證尚未申請（列入 TASKS 待辦）、
  roadmap 不設具體時間點
- 進行中：（無，本輪僅整理文件，未動程式碼）
- 下一步：依 TASKS.md 的 M1 開始修正三個致命問題 —— 修正 `get_frr()`、通知模組改寫為
  LINE Messaging API、`main.py` 補上常駐主迴圈
- 遇到的問題：LINE Messaging API 的串接測試需要使用者先申請 Channel Access Token / User ID，
  暫時只能先把 `enabled=false` 的安全略過邏輯做好
