# -*- coding: utf-8 -*-
"""systemd 放棄重啟機器人時的告警腳本（TASKS.md B2）。

由 `shuyu-lending-bot-alert.service` 觸發，而那個單元又是由主單元的
`OnFailure=` 掛上去的。要解的問題是：機器人停掉之後單元停在 `failed`，
**不會有任何人知道**。dry-run 下沒有代價，實單時「資金掛在交易所上、
機器人卻已經死了好幾小時而沒人知道」則不能接受。

**`OnFailure=` 每一次失敗都會觸發，不是只在 systemd 最後放棄時觸發**
（實測：`StartLimitBurst=2` 的單元一路失敗，告警被觸發 3 次，
分別在已重啟 0、1、2 次時）。設計這支腳本時原本以為重試中途屬於
`auto-restart` 狀態不會觸發，**實驗證明那是錯的**，見 DECISIONS.md D020。

因此腳本必須自己分辨三種情況，並且**永遠留下痕跡、不做靜音**：

- **已放棄**（`ActiveState=failed`）：可能是 30 分鐘內啟動次數用盡
  （`StartLimitBurst=4`），也可能是以 `EXIT_FATAL`（離開碼 2）退出而被
  `RestartPreventExitStatus=2` 擋下。兩種都是「人不介入就不會好」，
  訊息寫 CRITICAL、要求人工介入。
- **重試中**（`ActiveState=activating` / `SubState=auto-restart`）：
  訊息寫 ERROR、說明 systemd 正在重試第幾次。
- **當下正常**（`ActiveState=active` / `SubState=running`）：等 2 秒再查時單元
  已經在跑了。最常見的來源是**部署或手動 `systemctl restart`**——停掉舊容器
  那一刻會短暫觸發 `OnFailure=`（TASKS.md B4）。訊息寫 INFO（`NRestarts=0`）
  或 WARNING（`NRestarts>0`，代表確實失敗過但已自動恢復），都不要求人工介入。

第三種是後來補的。原本只有前兩種，`active/running` 沒有對應分支就落進「重試中」
的 else，於是**每次部署都送出一則「機器人啟動失敗」的 ERROR**，而單元其實好好的
（實際發生三次，時間都正好是重啟時刻）。這種假警報比漏報更陰險：它會訓練人
忽略這個管道，等到哪天推的是真的「已放棄」，看起來會跟前面幾十則一模一樣。

注意 `NRestarts` 是累計值，只有 `systemctl reset-failed` 會清零（CI 的 deploy job
每次部署前都會清）。所以「昨天崩過、今天部署」理論上會被歸到 WARNING 那一支——
訊息內容仍然誠實（它確實重啟過 N 次），只是稍微保守，可以接受。

不做靜音是刻意的：三者的代價不對稱。多送一則「正在重試」或「已恢復」只是稍微吵，
漏掉那則「已經放棄」卻等於整個 B2 白做。所以第三種降級為 INFO／WARNING、
但**仍然寫進日誌與 DB**，不是靜音。

**設計上的三個刻意選擇**：

1. **只用標準函式庫、不 import 專案任何模組**。理由與 `scripts/healthcheck.py`
   相同：這支腳本執行的時機正是「東西壞掉」的時候，它自己不能因為相依套件
   沒裝、或專案程式碼有問題而跟著爆掉。
2. **絕不寫 `bot_state.last_run_at`**。那個欄位是心跳，健康檢查靠它判斷機器人
   是否還活著。在機器人已經死掉的時候更新心跳，等於偽造它還活著。
3. **每個管道各自 try/except，一個失敗不影響其他**（與 `main._record_exit_reason`
   同一個原則）。DB 掛載掉了正是可能觸發這支腳本的原因之一，
   那時候更不能因為寫不進 DB 就連日誌也不留。

LINE 推播的位置已經留好（`send_line_push`），待 LINE Developers Channel 憑證
到位後填上即可，在那之前這支腳本負責的是「至少留下痕跡」。
"""

import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_UNIT = "shuyu-lending-bot.service"
# 主機端的金鑰檔（見 DECISIONS.md D022）。容器內是 /run/secrets/secrets.env，
# 但這支腳本跑在容器外，走的是原始路徑。
DEFAULT_SECRETS_FILE = "~/.config/bfx-lending-bot/secrets.env"
# 查詢單元狀態前先等一下，讓 systemd 把狀態轉換走完再問。
# 觸發告警與轉換到 auto-restart 幾乎同時發生，馬上問可能問到轉換前的舊狀態，
# 那會把「正在重試」誤判成「已經放棄」。正式部署的 RestartSec=30，
# 等這幾秒完全來得及；systemd 真的放棄時則永遠停在 failed，等多久都一樣。
DEFAULT_SETTLE_SECONDS = 2.0
# systemd 的欄位名 → 給人看的中文標籤
UNIT_PROPERTIES = {
    "Result": "失敗結果",
    "ExecMainStatus": "最後離開碼",
    "NRestarts": "已重啟次數",
    "ActiveState": "目前狀態",
    "SubState": "細部狀態",
}


def resolve_timezone():
    """本專案時區，查不到就退回 UTC（見 `utils/clock.py` 的同名邏輯）。

    **刻意與 `utils/clock.py` 重複**，不是疏漏：這支腳本由 systemd 在主機上直接執行，
    只用標準函式庫、不匯入專案任何模組（D024 的獨立實作原則——它跑在致命錯誤的
    告警路徑上，多一個 import 就多一個失敗點）。兩邊共用的只有環境變數名與預設值。
    """
    raw = os.getenv("BFX_TIMEZONE") or "Asia/Taipei"
    try:
        return ZoneInfo(raw)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def timestamp() -> str:
    """與機器人日誌同格式的時間戳，讓兩邊的行可以一起看。

    **原本這句話是假的。** 舊版用 `datetime.now()` 取本地時間，格式確實一樣，
    但這支腳本跑在主機（CST）、機器人跑在容器（UTC），於是兩邊寫進**同一個日誌檔**
    的時間差了 8 小時，而且行內看不出來是哪一個時區。現在兩邊都明確指定時區並附上
    `+0800` 偏移，這句 docstring 才真的成立。
    """
    moment = datetime.now(resolve_timezone())
    return f"{moment:%Y-%m-%d %H:%M:%S},{moment.microsecond // 1000:03d} {moment:%z}"


def push_timestamp() -> str:
    """推播訊息用的時間戳：秒為精度，仍帶時區偏移。

    比日誌少了毫秒——訊息是給人在手機上看的，毫秒沒有意義；偏移一定要留，
    這是 D028 的結論。格式與 `notify/messages.py` 的 `format_timestamp()` 一致，
    兩邊要一起改。
    """
    return datetime.now(resolve_timezone()).strftime("%Y-%m-%d %H:%M:%S %z")


def collect_unit_state(unit: str) -> dict:
    """問 systemd 這個單元是怎麼失敗的；問不到就回空的，不讓告警本身失敗。"""
    try:
        completed = subprocess.run(
            ["systemctl", "--user", "show", unit]
            + [f"--property={name}" for name in UNIT_PROPERTIES],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return {}

    state = {}
    for line in completed.stdout.splitlines():
        key, _, value = line.partition("=")
        if key in UNIT_PROPERTIES:
            state[key] = value
    return state


# classify() 的三種回傳值。刻意加 STATE_ 前綴：測試檔已經用 GAVE_UP／RETRYING
# 這兩個名字當「狀態字典」的樣本，同名會讓人讀錯。
STATE_GAVE_UP = "gave_up"
STATE_RETRYING = "retrying"
STATE_RUNNING_NOW = "running_now"


def classify(state: dict) -> str:
    """把單元當下的狀態歸成三種之一（見模組 docstring）。

    判斷依據是「現在還會不會再起來」而不是「這次失敗嚴不嚴重」：
    `activating` / `auto-restart` 代表下一次重啟已經排定、`active` / `running`
    代表它已經起來了、`failed` 才是真的停了。
    問不到狀態時**一律當成已放棄**——寧可多喊一次狼來了，也不要在機器人真的
    死掉時因為查不到狀態而靜悄悄放過。

    順序很重要：先判 `auto-restart`，再判 `running`，最後才落到 `failed`。
    反過來寫的話，重啟途中短暫的 `active` 會被誤判成「已恢復」。
    """
    if not state:
        return STATE_GAVE_UP
    if state.get("SubState") == "auto-restart":
        return STATE_RETRYING
    if state.get("ActiveState") == "active" and state.get("SubState") == "running":
        return STATE_RUNNING_NOW
    if state.get("ActiveState", "failed") == "failed":
        return STATE_GAVE_UP
    return STATE_RETRYING


def has_given_up(state: dict) -> bool:
    """systemd 是不是已經放棄、不會再自動重啟了。"""
    return classify(state) == STATE_GAVE_UP


def _restart_count(state: dict) -> int:
    """`NRestarts` 轉成整數；問不到或不是數字時當成 0（只影響訊息措辭）。"""
    try:
        return int(state.get("NRestarts", "0"))
    except (TypeError, ValueError):
        return 0


def build_message(unit: str, state: dict) -> str:
    """組出一行就看得懂發生什麼事的訊息。

    訊息必須誠實反映當下是「已放棄」還是「重試中」：`OnFailure=` 每次失敗都會
    觸發，中途那幾次若也寫成「不會再自動重啟」，看到的人會做出錯誤判斷。
    """
    details = "，".join(
        f"{label}={state[key]}" for key, label in UNIT_PROPERTIES.items() if key in state
    )

    outcome = classify(state)
    if outcome == STATE_GAVE_UP:
        message = (
            f"Bitfinex 放貸機器人已停止且 systemd 不會再自動重啟（單元 {unit} 停在 failed）。"
            "請人工介入：先看 `systemctl --user status` 與日誌確認原因，"
            "排除後以 `systemctl --user reset-failed` 清掉計數再啟動。"
        )
    elif outcome == STATE_RETRYING:
        restarts = state.get("NRestarts", "?")
        message = (
            f"Bitfinex 放貸機器人啟動失敗，systemd 正在自動重試（單元 {unit}，"
            f"已重啟 {restarts} 次）。次數用盡後會停在 failed 並再送一次告警。"
        )
    elif _restart_count(state) > 0:
        message = (
            f"Bitfinex 放貸機器人曾經失敗，但已自動恢復（單元 {unit} 目前 active/running，"
            f"已重啟 {state.get('NRestarts', '?')} 次）。不需人工介入，"
            "但建議查日誌確認當時的失敗原因。"
        )
    else:
        message = (
            f"告警被觸發，但單元 {unit} 目前正常運作中（active/running，尚未重啟過）。"
            "多半是部署或手動重啟過程中的短暫觸發，不需人工介入。"
        )

    return f"{message} 單元狀態：{details}" if details else message


def log_level(state: dict) -> str:
    """已放棄 CRITICAL、重試中 ERROR、當下正常 INFO／WARNING。

    這樣分是為了讓 `grep ERROR` 保持有意義——部署重啟造成的觸發若也寫成 ERROR，
    真正的故障就會淹沒在假警報裡（TASKS.md B4）。
    """
    outcome = classify(state)
    if outcome == STATE_GAVE_UP:
        return "CRITICAL"
    if outcome == STATE_RETRYING:
        return "ERROR"
    return "WARNING" if _restart_count(state) > 0 else "INFO"


# 三段式訊息用的常數。**這是 `notify/messages.py` 的第二份實作，不是複製貼上的疏忽**：
# 這支腳本跑在容器外、而且是在「容器可能正是壞掉的那一個」的前提下執行，所以只用
# 標準函式庫、不匯入專案任何模組（見模組 docstring 的設計選擇 1、TASKS.md P2-3）。
# **兩邊的規格要一起改**：分類、圖示、footer 的措辭都必須跟 `notify/messages.py` 一致，
# 否則同一支手機上會出現兩種長相的訊息，而那正是這次要修掉的問題。
PUSH_CATEGORY_SYSTEM = "系統"
PUSH_ABNORMAL_ICONS = {"WARNING": "🟡", "ERROR": "🟠", "CRITICAL": "🔴"}
PUSH_NORMAL_ICON = "🔵"
PUSH_FOOTER_ACTION_REQUIRED = "——— 需人工介入"
PUSH_FOOTER_NO_ACTION = "——— 無需處理"


def build_push_message(unit: str, state: dict) -> str:
    """組出推播用的三段式訊息（規格見 `notify/messages.py`）。

    **與 `build_message()` 分開是刻意的**：那一支給日誌與 DB 用，必須是**一行**——
    日誌是一筆一行的格式，塞進多行訊息會讓後續幾行看起來不像日誌，
    `grep ERROR` 也會漏掉它們。手機上要看的則是分行、有欄位、最後明講要不要動手的版本。
    同一個事件、兩種讀者，措辭一致但排版不同。
    """
    level = log_level(state)
    outcome = classify(state)
    restarts = state.get("NRestarts", "?")

    if outcome == STATE_GAVE_UP:
        headline = "機器人已停止，systemd 不會再自動重啟"
        fields = [
            ("單元", f"{unit}（停在 failed）"),
            ("影響", "機器人不在了，掛單留在交易所上沒有人管理"),
            ("處理方式", "先看 systemctl --user status 與日誌確認原因，"
                         "排除後以 systemctl --user reset-failed 清掉計數再啟動"),
        ]
        action_required = True
    elif outcome == STATE_RETRYING:
        headline = "機器人啟動失敗，systemd 正在自動重試"
        fields = [
            ("單元", unit),
            ("已重啟", f"{restarts} 次"),
            ("後續", "次數用盡後會停在 failed，並再送一次告警"),
        ]
        action_required = False
    elif _restart_count(state) > 0:
        headline = "機器人曾經失敗，但已自動恢復"
        fields = [
            ("單元", f"{unit}（目前 active/running）"),
            ("已重啟", f"{restarts} 次"),
            ("建議", "查日誌確認當時的失敗原因"),
        ]
        action_required = False
    else:
        # 這一支實際上不會被推出去（`send_line_push()` 對 INFO 一律回 False，見 D023），
        # 仍然組出來是為了 stdout 與測試看得到同一套措辭。
        headline = "告警被觸發，但單元目前正常運作中"
        fields = [
            ("單元", f"{unit}（active/running，尚未重啟過）"),
            ("研判", "多半是部署或手動重啟過程中的短暫觸發"),
        ]
        action_required = False

    details = "，".join(
        f"{label}={state[key]}" for key, label in UNIT_PROPERTIES.items() if key in state
    )
    if details:
        fields.append(("單元狀態", details))

    icon = PUSH_ABNORMAL_ICONS.get(level, PUSH_NORMAL_ICON)
    lines = [f"{icon}【{PUSH_CATEGORY_SYSTEM}】{headline}", f"時間：{push_timestamp()}"]
    lines.extend(f"{label}：{value}" for label, value in fields)
    lines.append(PUSH_FOOTER_ACTION_REQUIRED if action_required else PUSH_FOOTER_NO_ACTION)
    return "\n".join(lines)


def append_to_log(log_file: str, message: str, level: str = "CRITICAL") -> bool:
    """把事件補進機器人自己的日誌檔。

    用機器人的日誌格式（`時間 等級 訊息`）寫，這樣事後 grep ERROR 一次就能看到
    「機器人自己記錄的最後狀況」與「systemd 放棄的那一刻」兩件事。
    容器此時已經停了，不會有人跟這支腳本搶著寫同一個檔。
    """
    with open(log_file, "a", encoding="utf-8") as handle:
        handle.write(f"{timestamp()} {level} {message}\n")
    return True


def record_in_database(db_path: str, message: str) -> bool:
    """把事件寫進 `bot_state.last_action`。

    以 `mode=rw` 開啟：**檔案不存在就直接失敗，不要建立**。健康檢查已經因為
    同樣的理由用唯讀模式（見 `scripts/healthcheck.py` 的說明）——DB 掛載掉的時候，
    由旁邊的腳本順手把它補回來，只會把真正的問題蓋掉。

    只更新 `last_action`，**不碰 `last_run_at`**：那是心跳，機器人已經死了，
    更新它等於騙過健康檢查。
    """
    connection = sqlite3.connect(f"file:{db_path}?mode=rw", uri=True, timeout=5)
    try:
        with connection:
            connection.execute(
                "UPDATE bot_state SET last_action = ? WHERE id = 1",
                (message,),
            )
    finally:
        connection.close()
    return True


def load_secrets() -> dict:
    """從 `secrets.env` 讀出憑證，只用標準函式庫。

    這支腳本跑在**容器外**（主機端），systemd 的告警單元不會帶這兩個變數進來，
    所以要自己讀檔。**刻意不用單元的 `EnvironmentFile=`**：`secrets.env` 每一行
    都有 `export ` 前綴，systemd 會把 `export LINE_CHANNEL_ACCESS_TOKEN` 整串
    當成鍵名而解析失敗——那種失敗是安靜的，正好是這支腳本最不能有的性質。

    讀不到就回空字典：憑證沒設定不該讓告警腳本自己爆掉，日誌與 DB 兩個管道
    仍然要照常留下痕跡。
    """
    path = os.getenv("BFX_SECRETS_FILE") or os.path.expanduser(DEFAULT_SECRETS_FILE)
    secrets = {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[len("export "):]
                key, _, value = line.partition("=")
                secrets[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        return {}
    return secrets


def send_line_push(message: str, level: str = "CRITICAL") -> bool:
    """把告警推到 LINE（Messaging API push）。

    **INFO 一律不推**：那是部署重啟造成的觸發（D023），單元其實好好的。
    每次部署都推一則「告警」到手機，正是 B4 要消滅的那種假警報——
    在修掉它的同一支腳本裡又用另一個管道犯一次，沒有道理。
    日誌與 DB 仍然照常留痕，所以事後查得到。

    與 `notify/line_messaging.py` 是**兩份獨立實作**，不共用程式碼：這支腳本
    執行的時機正是「機器人壞掉」的時候，不能 import 專案模組、也不能依賴
    `requests`（見模組 docstring 的設計選擇 1）。兩邊要一起改，都寫了這段說明。
    """
    if level == "INFO":
        return False

    secrets = load_secrets()
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN") or secrets.get("LINE_CHANNEL_ACCESS_TOKEN")
    to_user_id = os.getenv("LINE_TO_USER_ID") or secrets.get("LINE_TO_USER_ID")
    if not token or not to_user_id:
        return False

    payload = json.dumps(
        {"to": to_user_id, "messages": [{"type": "text", "text": message[:5000]}]}
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.line.me/v2/bot/message/push",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status == 200
    except urllib.error.HTTPError as exc:
        # 只印狀態碼與 LINE 的說明，**絕不印出 token**
        print(f"LINE 推播失敗：HTTP {exc.code} {exc.read()[:200]!r}", file=sys.stderr)
        return False
    except Exception as exc:  # noqa: BLE001 - 連線層問題不該讓告警腳本自己失敗
        print(f"LINE 推播失敗（連線層）：{type(exc).__name__}: {exc}", file=sys.stderr)
        return False


def main() -> int:
    unit = os.getenv("BFX_UNIT") or DEFAULT_UNIT
    log_file = os.getenv("BFX_LOG_FILE")
    db_path = os.getenv("BFX_DB_PATH")

    settle_seconds = float(os.getenv("BFX_ALERT_SETTLE_SECONDS", DEFAULT_SETTLE_SECONDS))
    if settle_seconds > 0:
        time.sleep(settle_seconds)

    state = collect_unit_state(unit)
    message = build_message(unit, state)
    # 同一個事件、兩種讀者：日誌與 DB 要一行（grep 得到），手機要分行（看得懂）。
    push_message = build_push_message(unit, state)
    level = log_level(state)

    # stdout 一定會有一份：這支腳本由 systemd 執行，輸出會進 journal，
    # 就算下面兩個管道都失敗，至少 `systemctl --user status` 看得到。
    print(message)

    delivered = 0
    for name, action in (
        ("日誌檔", lambda: bool(log_file) and append_to_log(log_file, message, level)),
        ("資料庫", lambda: bool(db_path) and record_in_database(db_path, message)),
        ("LINE", lambda: send_line_push(push_message, level)),
    ):
        try:
            if action():
                delivered += 1
        except Exception as exc:  # noqa: BLE001 - 一個管道失敗不影響其他管道
            print(f"告警寫入{name}失敗：{exc}", file=sys.stderr)

    # 一個管道都沒送成才算這次告警失敗，讓它在 `systemctl --user status` 裡是紅的。
    # 沒設路徑（回 False）與寫入失敗（拋例外）都算沒送成——「以為有人會被通知，
    # 其實沒有」正是 B2 本身的問題，不能在告警機制裡再犯一次。
    if not delivered:
        print("所有告警管道都沒有送出，請檢查 alert 單元的環境變數與掛載路徑", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
