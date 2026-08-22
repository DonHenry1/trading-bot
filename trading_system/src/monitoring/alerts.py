"""
Alerting stub. Fill in your Telegram bot token / chat id via environment
variables named in config.yaml (monitoring.telegram_bot_token_env, etc.)
Not wired to a live bot yet — send_alert() logs locally until you add
your credentials and uncomment the HTTP call.
"""
from __future__ import annotations

import logging
import os

import requests

from src.config import MonitoringConfig

logger = logging.getLogger("alerts")


class AlertManager:
    def __init__(self, config: MonitoringConfig):
        self.config = config
        self.bot_token = os.environ.get(config.telegram_bot_token_env)
        self.chat_id = os.environ.get(config.telegram_chat_id_env)

    def send_alert(self, message: str, level: str = "info"):
        logger.log(logging.WARNING if level != "info" else logging.INFO, f"[ALERT:{level}] {message}")

        if not self.bot_token or not self.chat_id:
            logger.debug("Telegram credentials not set — alert logged locally only.")
            return

        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            requests.post(url, data={"chat_id": self.chat_id, "text": f"[{level.upper()}] {message}"}, timeout=5)
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")

    def alert_kill_switch(self, reason: str, detail: str):
        if self.config.alert_on.get("kill_switch", True):
            self.send_alert(f"KILL SWITCH: {reason} — {detail}", level="critical")

    def alert_drawdown_breach(self, drawdown_pct: float, limit_pct: float):
        if self.config.alert_on.get("drawdown_breach", True):
            self.send_alert(f"Drawdown breach: {drawdown_pct:.2%} (limit {limit_pct:.2%})", level="critical")
