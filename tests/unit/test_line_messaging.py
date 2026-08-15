# -*- coding: utf-8 -*-
"""`notify/line_messaging.py` 的單元測試。

這一層的價值不在「送得出去」（那要靠實測），而在**送不出去的時候不要把主程式拖下水**：
`send()` 出現在致命錯誤的退出路徑上，它若拋例外，原始錯誤與離開碼都會被蓋掉
（同 D019 的教訓）。所以每一種失敗方式都要有一條測試釘住「回傳 False、不拋例外」。

所有測試一律用替身，**不發真實請求**——真的送出去的話，會吃掉每月 200 則的額度，
而且測試照樣是綠的，只有使用者手機會響（見 conftest.no_real_line_credentials）。
"""

import pytest

from notify import line_messaging
from notify.line_messaging import LineNotifier


class FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


@pytest.fixture
def capture_post(monkeypatch):
    """攔下 requests.post，記錄呼叫內容並回傳可設定的假回應。"""
    calls = []

    def _install(response=None, raises=None):
        def fake_post(url, headers=None, json=None, timeout=None):
            calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
            if raises is not None:
                raise raises
            return response or FakeResponse()

        monkeypatch.setattr(line_messaging.requests, "post", fake_post)
        return calls

    return _install


def build(enabled=True, token="token-abc", to_user_id="U1234", logger=None):
    return LineNotifier(
        {"enabled": enabled, "token": token, "to_user_id": to_user_id}, logger
    )


class TestGuards:
    def test_disabled_never_sends(self, capture_post):
        calls = capture_post()
        assert build(enabled=False).send("訊息") is False
        assert calls == []

    def test_missing_token_warns_instead_of_sending(self, capture_post, fake_logger):
        calls = capture_post()
        assert build(token="", logger=fake_logger).send("訊息") is False
        assert calls == []
        assert any("未設定" in text for text in fake_logger.messages["warning"])

    def test_missing_user_id_warns_instead_of_sending(self, capture_post, fake_logger):
        calls = capture_post()
        assert build(to_user_id="", logger=fake_logger).send("訊息") is False
        assert calls == []
        assert any("未設定" in text for text in fake_logger.messages["warning"])


class TestSuccessPath:
    def test_posts_expected_request(self, capture_post):
        calls = capture_post()
        assert build().send("機器人已恢復正常巡檢。") is True

        (call,) = calls
        assert call["url"] == "https://api.line.me/v2/bot/message/push"
        assert call["headers"]["Authorization"] == "Bearer token-abc"
        assert call["headers"]["Content-Type"] == "application/json"
        assert call["json"] == {
            "to": "U1234",
            "messages": [{"type": "text", "text": "機器人已恢復正常巡檢。"}],
        }
        assert call["timeout"] == line_messaging.TIMEOUT_SECONDS

    def test_long_message_is_truncated_not_rejected(self, capture_post):
        # 超過 5000 字整包會被 LINE 退掉，寧可截斷也要把訊息送出去
        calls = capture_post()
        assert build().send("字" * 6000) is True
        text = calls[0]["json"]["messages"][0]["text"]
        assert len(text) == line_messaging.MAX_TEXT_LENGTH
        assert text.endswith("…")


class TestFailurePaths:
    @pytest.mark.parametrize(
        "status,keyword",
        [
            (401, "重新取得"),
            (403, "好友"),
            (404, "user ID"),
            (429, "額度"),
        ],
    )
    def test_http_errors_are_explained_not_just_numbered(
        self, capture_post, fake_logger, status, keyword
    ):
        # 半夜看到「HTTP 403」沒有任何幫助，要直接告訴人最可能的原因
        capture_post(FakeResponse(status_code=status, text='{"message":"..."}'))
        assert build(logger=fake_logger).send("訊息") is False
        logged = " ".join(fake_logger.messages["error"])
        assert f"HTTP {status}" in logged
        assert keyword in logged

    def test_connection_error_does_not_raise(self, capture_post, fake_logger):
        capture_post(raises=OSError("連線被拒"))
        # 這條是重點：send() 在致命錯誤的退出路徑上被呼叫，
        # 它自己拋例外會蓋掉原始錯誤並改掉離開碼
        assert build(logger=fake_logger).send("訊息") is False
        assert any("連線層" in text for text in fake_logger.messages["error"])

    def test_works_without_logger(self, capture_post):
        # 沒給 logger 也不能爆——通知層自己不該是壞掉的原因
        capture_post(FakeResponse(status_code=500))
        assert build(logger=None).send("訊息") is False

    def test_token_is_never_logged(self, capture_post, fake_logger):
        capture_post(FakeResponse(status_code=401, text="unauthorized"))
        build(token="super-secret-token", logger=fake_logger).send("訊息")
        assert "super-secret-token" not in " ".join(fake_logger.all_messages())


class TestEnvFallback:
    def test_env_is_used_when_config_is_empty(self, monkeypatch, capture_post):
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "env-token")
        monkeypatch.setenv("LINE_TO_USER_ID", "U-env")
        calls = capture_post()

        notifier = LineNotifier({"enabled": True, "token": "", "to_user_id": ""})
        assert notifier.send("訊息") is True
        assert calls[0]["headers"]["Authorization"] == "Bearer env-token"
        assert calls[0]["json"]["to"] == "U-env"
