# TASKS

> 勾選標記：`[ ]` 未開始／`[x]` 完成／`[~]` **部分完成**（做了但目標沒真的達成，
> 說明會寫在該項目底下）。

## 進行中

**分支 `refactor/m4-layering`（2026-08-15 開，從 main `b844d49`）**：
分層搬遷已完成，見 DECISIONS.md D021。行為零變動，283 項測試維持全過。

**M4 只剩 `feature/m4-line-messaging`**——被「使用者尚未申請 LINE Channel 憑證」卡住，
沒有其他技術阻塞。小額實單的前置條件仍是使用者補上 `secrets.env`。

（前一段：`deploy/m4-failure-alert`，2026-08-09，B2 與 A6 完成，見 D020，
測試 265 → 283 項；兩輪盤查累積的六項缺陷 A1～A6、B1～B3 至此全部清完。）

## 🔴 下一步・最高優先

### 2026-08-02 部署盤查發現的問題（PR #10 合併後驗收，依建議處理順序排列）

> **狀態更新（2026-08-02，分支 `deploy/m4-systemd-lifecycle`）**：**A1、A2 已完成**，
> 容器生命週期改由 systemd --user 的 Quadlet 單元管理，自動重啟與容器日誌都已實測生效
> （見 DECISIONS.md D017）。**A3～A5 經使用者指示延後**，已移到下方「延後處理」段落，
> 之後另開分支再做。A6 的前提隨 A1 完成而改變，處理方式見該項。

> **原摘要（保留備查）**：PR #10 加上的「容器可靠性四項」在程式碼層面都正確、
> 測試也都過，但**部署環境讓其中兩項（自動重啟、容器日誌）實際上不會生效**。
> 根因是容器的 conmon 行程被 CI job 收尾時一併殺掉了（A1）。
> A1 沒解決之前，機器人等於仍然沒有自動恢復能力——崩了就躺平，跟改之前一樣。
> **機器人本身運作正常**（心跳、落帳、日誌檔輸出都沒問題），這是維運層而非策略層的問題。

- [x] **A1（最高）：容器的 conmon 行程被殺，自動重啟與容器日誌實際上都沒有生效**
      —— **已於 2026-08-02 完成**，採下方「建議修法（方向 A）」。實際做法與驗證見
      DECISIONS.md D017；結果：`podman logs` 自 M3 以來第一次有內容、離開碼會傳回
      systemd、模擬 CI job 殺行程樹後 conmon 存活。以下為原始診斷紀錄，保留備查。
  - **現象**：`podman logs shuyu-lending-bot` 仍然完全沒有內容（改成 `k8s-file` 之後也一樣）。
  - **根因**：容器的 conmon 行程不存在。conmon 是 podman 為每個容器配的看門人行程，
    負責兩件事——把容器的 stdout/stderr 寫成日誌、在容器退出時依 `--restart` 規則重新拉起。
    `podman inspect` 記錄的 conmon PID 查無此行程，整台機器上沒有任何 conmon；
    容器主行程的父行程已變成 `systemd --user`（被認養的典型跡象）。
    容器建立於 17:35:35，runner 的 deploy job 於 17:35:42 完成，時間吻合。
  - **驗證方式（已實測，可重現）**：起兩個測試容器，指令都是「印一行 → 睡 15 秒 → 以離開碼 1 結束」，
    都帶 `--restart=on-failure:3 --log-driver=k8s-file`；其中一個在啟動後 `kill -9` 掉它的 conmon。

    | | conmon 活著 | conmon 被殺 |
    |---|---|---|
    | 容器退出後會重啟 | 會（RestartCount=1） | **不會（RestartCount=0）** |
    | `podman logs` | 有內容 | 停在 conmon 死亡那一刻 |
    | `podman ps` 狀態 | 準確 | **主行程已死仍顯示 running** |

  - **影響**：`--restart=on-failure:3` 完全不執行；`podman logs` 永遠是空的（換哪種
    log driver 都一樣）；`podman ps` / `podman inspect` 的狀態不可信。
    **不受影響的**：程式自己寫的 `logs/bfx_lending_bot.log`（跟 conmon 無關）、
    容器 healthcheck（由獨立的 systemd timer 執行 `podman healthcheck run`，實測仍每 60 秒正常執行）、
    機器人本身的巡檢與落帳。另外曾懷疑「沒人讀 stdout pipe 會塞住寫入端導致程式卡死」，
    **實測不成立**（灌 200KB 後程式仍正常跑完並以離開碼 0 結束）。
  - **這不是 PR #10 改壞的**：PR #8（M3）那版同樣由 CI 部署、同樣沒有 conmon，
    所以 `podman logs` 從 M3 起就一直是空的、重啟策略也從來沒生效過。
    PR #10 只是把問題查清楚了。
  - **建議修法（方向 A，推薦）**：**容器生命週期改由 systemd 管理，不再依附 CI job**。
    - 建立 Quadlet 單元 `~/.config/containers/systemd/shuyu-lending-bot.container`，
      把目前 workflow 裡 `podman run` 的參數（volume、環境變數、health 設定）搬進去。
    - 重啟策略改用 systemd 的 `Restart=on-failure` 搭配 `StartLimitIntervalSec` /
      `StartLimitBurst`，並**移除 `--restart=on-failure:3`**（兩者會打架）。
      順帶解掉一個 podman 版沒查清楚的疑點：`on-failure:N` 的計數在長期運行下
      會不會重置未經驗證，而 systemd 的「時間窗內幾次」語意明確得多。
    - CI 的 deploy job 改成只做兩件事：`podman build` 映像、`systemctl --user restart
      shuyu-lending-bot`。容器不再由 job 直接啟動，conmon 就不會跟著 job 收尾被清掉。
    - 依賴 A2 的 linger 才會在無登入 session 時持續運作。
  - **建議修法（方向 B，備案）**：想辦法讓 conmon 在 job 結束後存活（例如在 `podman run`
    前清掉 runner 用來追蹤子行程的環境變數）。改動只有一行，但屬於繞過 runner 的既定行為，
    runner 改版就可能再壞一次，且不解決「主機重開機後容器不會自己起來」。
  - **為什麼排最前面**：A1 沒解決，「自動重啟」就是假的，後面所有可靠性工作都建立在
    一個不成立的前提上；也直接擋住小額實單（實單期間崩潰無人恢復的風險不能接受）。

- [x] **A2（最高，且應先於 A1 完成）：`Linger=no`，登出後容器會整個消失**
      —— **已於 2026-08-02 完成**：執行 `loginctl enable-linger shuyu`，
      確認 `loginctl show-user shuyu` 顯示 `Linger=yes`。以下為原始紀錄。
  - **現象**：`loginctl show-user shuyu` 顯示 `Linger=no`。
  - **影響**：`systemd --user` 只在使用者還有登入 session 時存在。所有 session 結束後
    它會停止，**目前掛在它底下的容器會跟著沒掉**（容器主行程的父行程正是 `systemd --user`）。
    A1 的方向 A 改用 systemd user 單元後，同樣需要 linger 才能在無人登入時運作。
  - **建議修法**：`loginctl enable-linger shuyu`（一行指令，零風險）。
    做完以 `loginctl show-user shuyu | grep Linger` 確認變成 `Linger=yes`。
  - **為什麼排最前面**：一行指令、沒有副作用，而且是 A1 方向 A 的前提。

- [x] **A6：重新評估 `--health-on-failure=restart`**
      —— **已於 2026-08-09 完成**（分支 `deploy/m4-failure-alert`，見 DECISIONS.md D020）。
      觀察期結論：healthcheck 自 8/2 起每 60 秒執行、連續 7 天零誤判，據此決定開啟。
      採 **`HealthOnFailure=kill`** 而非 `restart`——kill 只負責殺掉不健康的容器，
      重啟仍然只由 systemd 負責，不會變成兩套機制並存。實測容器以離開碼 **137** 退出
      （不是 2），所以 `RestartPreventExitStatus=2` 不會誤擋這條路徑。
      以下為原始規劃紀錄，保留備查。
  - D016 原本的規劃是「先觀察一段時間，確認 healthcheck 不會誤判再開自動重啟」。
  - **A1 完成後的變化**：先前擔心的「conmon 不在，這個參數是否還執行得了」已不存在。
    而且「不健康就重啟」現在可以直接由 systemd 單元表達，不必用 podman 的參數
    （容器 healthcheck 由獨立的 systemd timer 執行 `podman healthcheck run`，
    要接上重啟只需讓失敗時 `systemctl --user restart` 該服務）。
  - **建議**：維持原本的觀察期規劃，累積一段實際運行資料、確認 healthcheck 不會誤判
    之後再開。開的時候走 systemd 那條路，不要回頭加 `--health-on-failure=restart`
    （會變成兩套重啟機制並存）。

### ✅ 已全部完成：A3～A5、B1～B3（2026-08-09）

> **這五項都不緊急、也不擋小額實單**，所以刻意集中到一條分支一次處理。
> 動手前不需要重新盤查——下面記的位置、成因與修法可直接照做。
>
> - **A3～A5**：PR #10 盤查時在**程式碼層**發現的。A3 只在 DB 本身故障時才會顯現、
>   A4 目前三條啟動路徑的 cwd 剛好都對、A5 純粹是設定檔少寫一行。
> - **B1、B2**：PR #12（systemd 接管容器）合併後驗收時發現的**維運層**問題。
>   B1 是這次自己加的 CI 檢查抓不到它想抓的東西；B2 是既有行為的缺口，
>   實單前值得補。兩項的完整背景見下方，也可參照 DECISIONS.md D017 的補充段。

- [x] **A3：`main.py` 的錯誤處理路徑中，落帳失敗會把原始錯誤蓋掉**
      —— **已於 2026-08-09 完成**（分支 `fix/m4-code-audit-findings`）：抽出
      `_record_exit_reason()` 供三處共用，落帳失敗只記日誌。順帶把 `finally` 的
      `repository.close()` 也包起來——它拋例外同樣會取代回傳值，離開碼直接變成 1。
      補 4 條測試（`TestExitPathSurvivesBrokenDatabase`），並實際還原 `main.py`
      反證過這 4 條在沒有修正時全部失敗。以下為原始診斷紀錄，保留備查。
  - **位置**：`main.py` 三處 —— 啟動檢查失敗（約 160 行）、`FatalError`（約 177 行）、
    未預期例外（約 192 行），都是先 `repository.save_state(...)` 再 `notifier.send(...)`。
  - **問題**：如果**資料庫本身故障**（磁碟滿、DB 損毀、volume 掛載掉了），`save_state()`
    會拋出新的例外，後果是三層的：原始錯誤訊息遺失、`notifier.send()` 不會執行、
    離開碼從刻意設計的 2（`EXIT_FATAL`）變成 1。`FatalError` 那條路徑更糟——
    新例外會被下方的 `except Exception` 接住，直接被誤判成「未預期的例外」。
  - **為什麼值得修**：「volume 掛載掉了」正是這個部署真實會發生的情況之一
    （M3 起部署失敗的根因就是主機端目錄不存在），而那時候最需要的就是看到原始錯誤。
  - **建議修法**：把三處落帳各自包一層 `try/except Exception`，寫不進去就只記日誌
    （例如 `logger.error(f"退出前落帳失敗，原始錯誤為：{exc}")`），不讓它影響離開碼與通知。
    可抽成一個小的 `_record_exit_reason(logger, repository, reason)` 私有函式，三處共用。
    測試補一條：`save_state` 被設定成一定拋例外時，離開碼仍為 `EXIT_FATAL` 且通知照送。

- [x] **A4：資料庫路徑的解析方式，主程式與健康檢查兩邊不一致**
      —— **已於 2026-08-09 完成**（分支 `fix/m4-code-audit-findings`）：`db/repository.py`
      新增 `PROJECT_ROOT` 與 `resolve_db_path()`，相對路徑一律相對專案根目錄，
      並比照 healthcheck 讓 `BFX_DB_PATH` 有最高優先權（原本只有 healthcheck 認得它，
      設了就會兩邊分家，是同一個缺陷的另一面）。補 6 條測試，其中兩條直接斷言
      「主程式與 healthcheck 對同一份設定算出同一個路徑」。
      兩支檔案刻意不互相 import——healthcheck 要維持零專案相依、零副作用，
      改任一邊都要一起改，兩邊的 docstring 都寫了這件事。以下為原始診斷紀錄，保留備查。
  - **位置**：`db/repository.py` 的 `Repository.from_config()` 對相對路徑是相對
    **當下工作目錄（cwd）**；`scripts/healthcheck.py` 的 `resolve_db_path()` 是相對
    **程式所在目錄（`scripts/` 的上一層）**。
  - **現況不會出錯**：容器 `WORKDIR=/app`、`start.sh` 有 `cd "$ROOT_DIR"`、
    `systemd/bfx-lending-bot.service` 有 `WorkingDirectory=`，三條路徑的 cwd 剛好都對。
  - **風險**：任何一天有人從別的目錄啟動主程式，主程式會在別處建立 DB，
    健康檢查則仍去專案目錄找 —— 結果是**健康檢查永遠回報「尚未寫入任何心跳」**，
    而機器人其實跑得好好的。這種錯誤很難聯想到路徑上。
  - **建議修法**：讓 `Repository` 也以專案根目錄解析相對路徑（與 healthcheck 一致），
    或反過來讓兩邊共用同一個解析函式。前者較好，因為「設定檔寫的相對路徑相對於專案」
    比「相對於誰啟動它」更符合直覺。改完補一條測試釘住行為。

- [x] **A5：`config.yaml` 沒有列出 `engine.health_max_silence_seconds`**
      —— **已於 2026-08-09 完成**（分支 `fix/m4-code-audit-findings`）：在 `engine:`
      區段補上註解掉的設定與說明（不設就是 `interval_seconds × 3 + 60`）。
      以下為原始診斷紀錄，保留備查。
  - **問題**：這個可以覆寫健康檢查門檻的設定只有程式碼與 DECISIONS.md D016 知道，
    設定檔裡完全看不到，等於藏起來的選項。
  - **建議修法**：在 `config.yaml` 的 `engine:` 區段補上一行（註解掉或給預設值皆可），
    說明「不設就是 `interval_seconds × 3 + 60`」。

- [x] **B3：那道檢查的 `podman logs` 斷言寫錯，從加進來就不可能通過**
      —— **已於 2026-08-09 完成**（分支 `fix/m4-ci-lifecycle-assertion`，見 DECISIONS.md D018）
  - **現象**：PR #13 合併後 deploy job 紅燈，訊息是「30 秒內 podman logs 仍然沒有內容，
    conmon 或 log driver 有問題」。但實查之下 conmon 在、cgroup 正確、`podman logs`
    有 11 行內容——**三件事全都是好的，壞的是檢查**。
  - **根因**：機器人的日誌走 **stderr**（`utils/logger.py` 的 `logging.StreamHandler()`
    不帶參數，Python 預設就是 stderr），而程式沒有任何 `print()`，所以容器 stdout 永遠是空的。
    檢查寫的是 `$(podman logs ... 2>/dev/null)`——`$( )` 只捕捉 stdout、`2>/dev/null`
    又把 stderr 丟掉，等於親手扔掉自己要找的東西。
  - **影響**：deploy job 自 PR #12 合併（2026-08-02）以來一路是紅的，只是沒人注意到。
    當時手動驗收看得到日誌，是因為終端機下 stderr 會直接顯示在螢幕上。
    **機器人本身不受影響**，重啟服務在這一步之前就已完成。
  - **修法**：改用 `CONTAINER_LOGS=$(podman logs --tail=20 ... 2>&1)`，並同時要求
    podman 指令本身成功（否則「no such container」的錯誤訊息會被當成日誌而誤放行）。
    刻意**不改 `utils/logger.py`**——為了讓寫錯的斷言通過而改動機器人輸出行為，因果顛倒。

- [x] **B1：CI 那道「驗證容器生命週期真的由 systemd 接管」的檢查，抓不到它想抓的迴歸**
      —— **已於 2026-08-09 完成**，與 B3 同一個步驟一起改（分支
      `fix/m4-ci-lifecycle-assertion`，見 DECISIONS.md D018）。實測：正式容器通過（離開碼 0）、
      直接 `podman run` 起的假容器紅燈（離開碼 1，被 cgroup 判斷擋下）。
      關鍵在於那個假容器的 `podman logs` **是有內容的**，所以它是被「啟動方式不對」擋下，
      不是碰巧因為沒日誌而失敗。以下為原始診斷紀錄，保留備查。
  - **先看懂背景**（不熟 podman 的人請先讀這段）：
    - **conmon** 是 podman 為每個容器配的「看護」行程，只做兩件事——把容器的
      stdout/stderr 抄成日誌（`podman logs` 讀的就是這份），以及在容器退出時
      依重啟規則把它拉起來。**conmon 不在，這兩件事就都沒人做**，
      但容器本身還會繼續跑，所以外觀上看不出異狀。
    - **cgroup** 是 Linux 幫每個行程登記的「群組歸屬」。重點在於：系統清理行程時
      是**整個 cgroup 一起清掉**，不是一個一個殺。
    - **原本壞掉的原因**（A1，已修）：舊做法是 CI 的 deploy job 自己 `podman run`，
      於是 conmon 的 cgroup 登記在 **CI job 那一群**底下。job 收尾時整群被清掉，
      conmon 跟著死。所以日誌永遠是空的、容器崩了也沒人重啟。
      改由 systemd 啟動之後，conmon 的 cgroup 變成
      `user@1000.service/app.slice/shuyu-lending-bot.service/runtime`，與 job 無關。
  - **問題**：PR #12 在 deploy job 加了一步「驗證容器生命週期真的由 systemd 接管」，
    用意是「**萬一以後有人改回 `podman run`，要當場紅燈**」。但它斷言的兩件事是
    「conmon 行程存在」與「`podman logs` 有內容」，而**這兩件事在舊的壞掉做法下也會通過**：
    舊做法的 conmon 是在 **job 收尾那一刻**才被清掉的，而這道檢查跑在 **job 執行期間**，
    那時 conmon 還活著、`podman logs`（k8s-file 驅動）也讀得到東西。
  - **所以現況是**：這道檢查擋得住「服務起不來、映像不存在、log driver 壞掉」，
    但**擋不住它最想擋的那件事**。不是會造成故障的 bug，是一道給錯安全感的防線。
  - **建議修法**（很小）：不要只問「conmon 在不在」，要問「**conmon 的 cgroup 屬於誰**」。
    那段程式已經用 `cat /proc/$CONMON_PID/cgroup` 把 cgroup 印出來了，只是印出來給人看、
    沒有拿去比對。補一個判斷即可：
    ```bash
    CONMON_CGROUP=$(cat "/proc/$CONMON_PID/cgroup")
    case "$CONMON_CGROUP" in
      *shuyu-lending-bot.service*) ;;   # 由 systemd 啟動，正確
      *) echo "::error::conmon 不在 shuyu-lending-bot.service 的 cgroup 底下"
         echo "::error::容器可能又變回由 CI job 直接 podman run 啟動：$CONMON_CGROUP"
         exit 1 ;;
    esac
    ```
    這個差異**在 job 執行期間就看得出來**，不必等收尾，所以才抓得到。
  - **位置**：`.github/workflows/python-app.yml`，deploy job 的
    「驗證容器生命週期真的由 systemd 接管」步驟（`cat "/proc/$CONMON_PID/cgroup"` 那行後面）。
  - **驗收方式**：改完之後，可以另起一個用 `podman run` 直接啟動的同名測試容器，
    確認新的判斷會失敗（模擬「有人改回舊做法」）；正式容器則應通過。

- [x] **B2：systemd 放棄重啟時，沒有任何人會被通知**
      —— **已於 2026-08-09 完成**（分支 `deploy/m4-failure-alert`，見 DECISIONS.md D020）。
      採方向 A：主單元掛 `OnFailure=`，新增告警單元與主機端 `scripts/notify_failure.py`。
      **實驗推翻了規劃時的假設**：`OnFailure=` 是每次失敗都觸發，不是只在最後放棄時
      觸發（實測 `StartLimitBurst=3` 觸發 4 次），所以腳本自己查單元狀態分辨
      「重試中」（ERROR）與「已放棄」（CRITICAL）。LINE 位置已留好，待憑證。
      以下為原始診斷紀錄，保留備查。
  - **現況**：Quadlet 單元設的是 `Restart=on-failure` +
    `StartLimitIntervalSec=1800` / `StartLimitBurst=4`，也就是「30 分鐘內最多 4 次啟動，
    超過就停手」。這個上限是**刻意的**——金鑰無效這類問題重開幾次都不會好，
    無限重啟只會洗版（見 D016、D017）。
  - **問題**：systemd 放棄之後單元停在 `failed`，機器人整個不在了，
    但**不會有任何通知**。要自己下 `systemctl --user status` 才會發現。
    容器 healthcheck 也幫不上忙——容器都沒了，沒有東西可以檢查。
  - **這不是這次改壞的**：舊的 `--restart=on-failure:3` 同樣沒有通知，
    只是當時它根本沒在執行（A1），所以問題沒浮現。
  - **為什麼實單前要補**：dry-run 下機器人躺平沒有代價，實單時「資金掛在交易所上、
    機器人卻已經死了好幾小時而沒人知道」是不能接受的。
  - **建議修法（方向 A，推薦）**：在 Quadlet 單元的 `[Unit]` 加
    `OnFailure=shuyu-lending-bot-alert.service`，另寫一個 oneshot 單元負責送通知。
    systemd 的 `OnFailure=` 正是為這種情境設計的，單元進入 failed 就會觸發一次。
    **注意這條會被 LINE 通知的進度卡住**——`modules/line_notifier.py` 目前打的是
    已停用的 LINE Notify 端點，通知一定失敗（見下方 M4 的 `feature/m4-line-messaging`）。
    在憑證到位之前，退而求其次可以先讓 alert 單元把事件寫進
    `logs/bfx_lending_bot.log` 或 DB 的 `bot_state.last_action`，至少留下痕跡。
  - **建議修法（方向 B，備案）**：不靠 systemd，改讓外部定時檢查
    （例如既有的 healthcheck timer 之外再加一個）發現服務不在就告警。
    比較繞，且多一個要維護的元件，除非方向 A 遇到阻礙否則不建議。
  - **一併決定**：修這條的時候順便把 A6（不健康就自動重啟）想清楚——兩者都是
    「systemd 層的失效處理」，設計上會互相牽動，分開做容易做出打架的規則。

## 待處理（依優先級，對應 PLAN.md 的 M1～M4）

### M1：修正致命問題
- [x] 修正 `get_frr()`：改抓 Bitfinex V2 `GET /v2/ticker/fUSD` 的 FRR 欄位（原本用
      `fetch_funding_rate` 讀到永續合約資金費率，數據錯誤，不是真正的放貸 FRR）
      （2026-07-26，分支 `fix/m1-frr-and-loop`）
- [x] `main.py` 加入 `while True` 主迴圈 + `time.sleep(interval)` + 例外分類隔離
      （`RetryableError` / `FatalError` / `SkipCycleError`，見 `utils/exceptions.py`）
      （2026-07-26，分支 `fix/m1-frr-and-loop`）

### M2：補策略與風控
- [x] `cancel_active_offers()` 真正實作取消未成交掛單，改用 Bitfinex V2 raw API
      （`private_post_auth_r_funding_offers_symbol` 查詢 + `private_post_auth_w_funding_offer_cancel`
      取消），原本誤用 `fetch_open_orders` 查錯訂單類型、且從未真的取消
      （2026-07-26，分支 `feature/m2-strategy-and-risk`）
- [x] `create_loan_offer()` 改走 raw API（`private_post_auth_w_funding_offer_submit`，
      `type="LIMIT"`），原本檢查的 `create_funding_offer`/`createFundingOffer` 在 ccxt
      裡從未存在過，實盤模式下必定失敗（2026-07-26，見 DECISIONS.md D010）
- [x] 掛單更新機制：改為「每輪全取消重掛」，`run_once()` 補上 `cancel_active_offers()`
      呼叫與 `cancel_settle_seconds` 等待。原需求寫的「只補掛差額」前提有誤（funding 錢包
      的 `free` 本來就已扣除掛單與已放貸金額），實質問題是舊掛單利率落後市場
      （2026-07-26，見 DECISIONS.md D011）
- [x] 策略層補多筆階梯利率（spread）：百分比遞增（`spread_step_pct`）、金額均分、餘數併入
      第一筆、筆數依 `min_loan_size_usd` 自動降階、每筆各自判斷天期
      （2026-07-26，見 DECISIONS.md D011）
- [x] 補 `maxtolend` / `maxpercenttolend` 風控上限檢查（單輪量控版，觸及上限縮量掛；
      預設 0 = 不限制）（2026-07-26，見 DECISIONS.md D011）

### M3：資料與可觀測
- [x] 建立 `db/`（`models.py` + `repository.py`），SQLite WAL 模式，記錄
      `loan_offers`、`earnings_daily`、`bot_state`
      （2026-07-27，分支 `feature/m3-data-and-observability`）
- [x] `utils/logger.py` 改用 `RotatingFileHandler`，並移除 `logger.py`／`start.sh` 兩處的
      檔名時間戳邏輯——常駐後每次重啟另起一串新檔的話，`backup_count` 形同沒有上限
      （2026-07-27，見 DECISIONS.md D013）
- [x] 建立 `api/rate_limiter.py`：`with_retry` decorator，指數退避重試。攔的是
      `exchange_client` 已分類好的 `RetryableError` 而非 ccxt 原始例外，因此一行即可套用；
      `create_loan_offer()` 刻意不套（掛單不冪等，重試會重複借出）
      （2026-07-27，見 DECISIONS.md D013）
- [x] 補 heartbeat（`bot_state.last_run_at`，每輪含略過都更新）與連續 N 次失敗告警
      （`FailureTracker`，只在跨門檻與恢復時各送一次）（2026-07-27，見 DECISIONS.md D013）
- [ ] 評估把 `maxtolend` 從「單輪量控版」升級為「含已放貸的真實總曝險版」：需每輪查詢
      `private_post_auth_r_funding_credits_symbol`（已被借走）與
      `private_post_auth_r_funding_loans_symbol`（已出借未被借走），這兩份查詢結果 DB 也用得到
      （2026-07-26 決定延後，見 DECISIONS.md D011）
- [ ] 接上 `earnings_daily` 的資料來源：新增查詢 Bitfinex ledger
      （`/v2/auth/r/ledgers/{ccy}/hist`）取得利息入帳紀錄，餵給既有的
      `upsert_daily_earning()`。M3 只建了表與介面，尚無呼叫端；dry-run 下無法驗證正確性，
      建議與小額實單測試一起做（2026-07-27 決定延後，見 DECISIONS.md D013）

### M4：架構重構、測試與部署（依 DECISIONS.md D015 拆成子分支）
- [x] **子分支 `refactor/m4-layering`**（2026-08-15）：依 ARCHITECTURE.md 完成目錄搬遷，
      `modules/` 已移除。四個檔案以 `git mv` 搬到 `api/`／`strategies/`／`notify/`，
      新增 `api/base.py`、`strategies/base.py`、`core/bot_engine.py`，
      `main.py` 縮為純 bootstrap（227 → 60 行）。類別更名 `LendingStrategy` →
      `FrrPlusStrategy`，見 DECISIONS.md D021。`scripts/` 兩支維運腳本依原訂不搬。
      283 項測試全過（含 live）、`py_compile` 全過、dry-run 實跑 `main.py` 驗過一輪。
      **`notify/line_messaging.py` 只搬了位置，內容仍是已停用的 LINE Notify**，
      改寫仍屬 `feature/m4-line-messaging`
- [x] 建立 `tests/unit`、`tests/functional`、`tests/integration` 目錄與測試，共 227 項
      （2026-08-01，分支 `test/m4-test-suite`）。一併補掉三個 CI 缺口：拿掉
      `pytest ... || true`（測試失敗必須擋下合併）、新增 `requirements-dev.txt`
      取代臨時的 `pip install pytest`、把 workflow 內嵌的 heredoc smoke test 收斂進
      `tests/integration/test_dry_run_cycle.py`
- [x] 修正 `upsert_daily_earning()` 的 `principal_avg` 缺陷（2026-08-01，測試抓到）：
      `db/models.py` 宣告 `NOT NULL` 但函式簽章預設 `None` 且 ON CONFLICT 用了
      `COALESCE`，NOT NULL 在衝突解析前先擋下，導致首次插入與後續累加兩條路徑都必定
      `IntegrityError`。改為 `principal_avg REAL`；當時尚無任何 DB 檔存在，遷移成本為零
- [ ] **子分支 `deploy/m4-podman`**：收斂部署路線為 Podman 容器化（見 DECISIONS.md D007）：
      - [x] 修正部署一直失敗的主機端目錄問題（2026-08-01）：podman 的 bind mount 不會
            自動建立主機端目錄，`.../ShuyuLendingBot/data` 從未存在，deploy job 自 M3
            加上該 volume 起每次都以 exit code 125 失敗。workflow 補 `mkdir -p` 一步
      - [ ] 補 `secrets.env` 到部署目錄（`/workspace/deploy/active-bots/ShuyuLendingBot/`）。
            目前該檔不存在，`dry_run: true` 下不影響，**實單前必須補上**（使用者端待辦）
      - [x] `podman logs` 取不到內容：改用 `--log-driver=k8s-file`（含 `max-size=10mb`），
            CI 的「取得最近容器日誌」改讀掛載出來的 `logs/bfx_lending_bot.log`
            （2026-08-02，分支 `deploy/m4-podman-hardening`）。
            **當時判定的根因（journald 在 rootless 下拿不到）是錯的**，
            真正原因是 conmon 被殺；**改由 systemd 管理容器後才真正解決**
            （2026-08-02，分支 `deploy/m4-systemd-lifecycle`，見 A1 與 D017）。
            現在 `podman logs` 自 M3 以來第一次取得到內容
      - [x] 清理 `logs/` 底下 M3 之前產生的帶時間戳舊檔（部署目錄 7 個、專案目錄 4 個），
            刪前確認全是 dry-run 常規巡檢、無 ERROR/CRITICAL（2026-08-02）
      - [x] 容器崩潰重啟策略：原採 `--restart=on-failure:3`（次數上限），
            `docker-compose.yml` 同步由 `unless-stopped` 改為 `on-failure`（2026-08-02）。
            **podman 端的參數正確但實際不會執行**（conmon 不在就沒人觸發重啟），
            已改由 systemd 表達並移除 `--restart=on-failure:3`：
            `Restart=on-failure` + `StartLimitIntervalSec=1800` / `StartLimitBurst=4`
            （2026-08-02，分支 `deploy/m4-systemd-lifecycle`，見 D017）。實測生效
      - [x] `FatalError` 與自動重啟的衝突：`main.py` 離開碼語意化為
            `EXIT_OK=0` / `EXIT_UNEXPECTED=1` / `EXIT_FATAL=2`，三條退出路徑退出前
            都先把原因寫進 `bot_state.last_action`（2026-08-02）。
            原本受限於「podman restart policy 看不到離開碼」，只能靠次數上限節流；
            改由 systemd 管理後已能直接用 `RestartPreventExitStatus=2` 表達
            「EXIT_FATAL 就不重啟」，實測 `NRestarts=0`（見 D017）
      - [x] 容器 healthcheck：新增 `scripts/healthcheck.py`，唯讀讀取
            `bot_state.last_run_at` 判斷心跳是否過期（門檻 = 巡檢間隔 × 3 + 60 秒）。
            **刻意不看 `consecutive_failures`**——那是交易所端的問題，重啟容器無益，
            已由 `FailureTracker` 告警負責（2026-08-02，見 DECISIONS.md D016）
      - [ ] 觀察期滿後評估「不健康就自動重啟」—— **見上方 A6**。A1 完成後改走
            systemd 那條路表達，不要回頭加 `--health-on-failure=restart`
      - [x] PR #10 合併後確認正式容器已套用新參數（2026-08-02 驗收）：
            `on-failure`（上限 3 次）／`k8s-file`／健康狀態 `healthy` 都已套用，
            healthcheck 每 60 秒實際執行且離開碼 0。**但 `podman logs` 仍為空**，
            由此查出 A1
      - [x] 容器生命週期改由 systemd --user 的 Quadlet 單元管理（2026-08-02，
            分支 `deploy/m4-systemd-lifecycle`，見 D017）：新增版控的
            `systemd/shuyu-lending-bot.container`、CI deploy job 改為
            `podman build` + 更新單元 + `systemctl --user restart`、開啟 linger、
            掛載目錄的 `mkdir -p` 移進 `ExecStartPre`、新增「驗證生命週期由 systemd
            接管」的 CI 斷言步驟（服務 active／conmon 存在／`podman logs` 有內容）
      - 確認 `systemd/bfx-lending-bot.service` 的去留：D016 已決定維持本機測試用途，
        正式路線不採 `podman generate systemd`（改採 Quadlet，見 D017）；
        檔案本身的去留仍待確認。注意勿與新增的
        `systemd/shuyu-lending-bot.container` 混淆——後者才是正式部署路線
- [ ] 小額真金測試前，再次確認 API Key 權限已禁止「提現（Withdraw）」
- [ ] **子分支 `feature/m4-line-messaging`**：改寫 `notify/line_messaging.py` 的內容，走 LINE Messaging API
      （檔案位置已於 2026-08-15 的分層搬遷就位，只差內容） push
      （取代已停用的 LINE Notify）—— 原列在 M1，2026-07-26 使用者指示改排到最後一步；
      **被下方使用者端待辦卡住，尚無法實測**。一併注意 `config/settings.py` 讀的環境變數
      名還是舊的 `LINE_NOTIFY_TOKEN`／`LINE_NOTIFY_CHANNEL`，要同步改成
      `LINE_CHANNEL_ACCESS_TOKEN`／`LINE_TO_USER_ID`（2026-07-27 於 M3 發現）
- [ ] 清理已合併完成的殘留分支：`fix/m1-frr-and-loop`、`feature/m2-strategy-and-risk`、
      `docs/sync-m2-branch-workflow`、`feature/roadmap-and-tests`（本地與遠端）
      （2026-07-27 使用者選擇先不處理）

## 基礎建設待辦（使用者端）
- [ ] 申請 LINE Developers Channel，取得 `Channel Access Token` 與 `User ID`
      （目前尚未申請，是 LINE 通知模組串接測試的前置阻塞項目）

## 已完成
- [x] 設定 git `user.name` / `user.email` 為 `Chen-shuyu` / `suyuchen322@gmail.com`
      （原本所有 commit 作者都是 `shuyu <shuyu@localhost.localdomain>`，GitHub 關聯不到帳號）
      （2026-07-27）
- [x] `.gitignore` 補上 `data/` 與 `*.sqlite3` 系列：原本完全沒排除，M3 建立的 SQLite 檔
      會被 commit 進 git（2026-07-27）
- [x] `podman run` 與 `docker-compose.yml` 補掛 `/app/data` volume，否則每次重新部署
      SQLite 紀錄就歸零（2026-07-27）
- [x] 調查 ccxt 第三方套件在 Bitfinex funding 功能上的可靠性，決定往後統一的呼叫方式：
      確認 ccxt 對 Bitfinex funding 從未實作過統一（unified）方法（非版本移除），一律改走
      raw/implicit API；同時查證 Bitfinex 官方 REST 文件，盤點 19 個 funding 端點規格，
      逐一比對現有程式碼用法。結論記錄為 DECISIONS.md D010，詳細盤點見
      `.project-docs/CCXT_BITFINEX_API_INVESTIGATION.md`（2026-07-26）
- [x] 修正 `test_connection()`：`fetch_balance()` 補上 `type="funding"`，與
      `get_available_balance()` 查詢同一個錢包（2026-07-26，見 DECISIONS.md D010）
- [x] PRD.md／SHUYU_PROJECT_PLAN.md 規劃書撰寫，含附錄 B 實作指引（2026-07-14）
- [x] dry-run 雛型：`main.py` 單次執行流程、`config/settings.py` 讀取、
      `modules/lending_strategy.py` 策略骨架（門檻/拆單/天期判斷）（2026-07-14 之前）
- [x] CI workflow 骨架 `.github/workflows/python-app.yml`（test/integration/deploy 三個 job）
      （2026-07-14）
- [x] `.project-docs/` 文件結構建立，舊規劃書內容分類歸位（2026-07-26）
- [x] 修正 `ccxt.bitfinex2`（已於目前釘選的 ccxt 版本移除）改用 `ccxt.bitfinex`，並修正
      `get_available_balance()` 未指定 `type: "funding"`、解析格式對不上新版 ccxt 統一
      balance 結構的問題（意外發現，見 DECISIONS.md D009）（2026-07-26）
- [x] 同步調整 CI smoke test：`main()` 已變成常駐迴圈不會自己返回，smoke test 改為呼叫
      `run_once()` 跑單輪（2026-07-26）
