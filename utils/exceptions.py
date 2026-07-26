# -*- coding: utf-8 -*-
"""主迴圈使用的例外分類，對應 archive/SHUYU_PROJECT_PLAN.md 附錄 B.7 的例外映射表。"""


class RetryableError(Exception):
    """可重試的暫時性錯誤，例如速率限制、網路逾時、伺服器 5xx。"""


class FatalError(Exception):
    """不可重試的致命錯誤，例如 API 金鑰無效、權限不足、簽章錯誤。"""


class SkipCycleError(Exception):
    """本輪應跳過但不視為錯誤，例如餘額不足門檻、FRR 取不到有效值。"""
