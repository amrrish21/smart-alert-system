"""
notifier.py — Notification Handlers
Smart Automated Notification & Alerts System

Supported channels
------------------
- SMS via Twilio
- Discord Webhook
- Telegram Bot API
"""

import logging
import os
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class AlertPayload:
    """Structured data passed to every notification handler."""

    product_title: str
    product_url: str
    current_price: Optional[float]
    threshold_price: Optional[float]
    in_stock: bool
    trigger_reason: str          # Human-readable sentence explaining the alert


class NotificationError(Exception):
    """Raised when a notification channel fails to deliver the message."""


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _build_message(payload: AlertPayload) -> str:
    """Return a plain-text alert message suitable for SMS / chat."""
    price_line = (
        f"💰 Current price : ${payload.current_price:.2f}\n"
        f"🎯 Your threshold: ${payload.threshold_price:.2f}"
        if payload.current_price is not None and payload.threshold_price is not None
        else "💰 Price data unavailable"
    )
    stock_icon = "✅ IN STOCK" if payload.in_stock else "❌ OUT OF STOCK"
    return (
        f"🚨 PRICE ALERT — {payload.product_title}\n\n"
        f"{payload.trigger_reason}\n\n"
        f"{price_line}\n"
        f"📦 Availability: {stock_icon}\n\n"
        f"🔗 {payload.product_url}"
    )


def _build_discord_embed(payload: AlertPayload) -> dict:
    """Return a rich Discord embed object."""
    colour = 0x00B94A if payload.in_stock else 0xE5002B
    fields = [
        {
            "name": "Current Price",
            "value": f"${payload.current_price:.2f}" if payload.current_price else "N/A",
            "inline": True,
        },
        {
            "name": "Threshold",
            "value": f"${payload.threshold_price:.2f}" if payload.threshold_price else "N/A",
            "inline": True,
        },
        {
            "name": "Availability",
            "value": "✅ In Stock" if payload.in_stock else "❌ Out of Stock",
            "inline": True,
        },
    ]
    return {
        "embeds": [
            {
                "title": f"🚨 Alert: {payload.product_title}",
                "description": payload.trigger_reason,
                "url": payload.product_url,
                "color": colour,
                "fields": fields,
                "footer": {"text": "Smart Alert System • github.com/your-handle"},
            }
        ]
    }


# ---------------------------------------------------------------------------
# Notifier class
# ---------------------------------------------------------------------------

class Notifier:
    """
    Unified notification dispatcher.

    Credentials are read exclusively from environment variables — never
    accepted as constructor arguments — to prevent accidental exposure in
    logs or version control.

    Environment variables
    ---------------------
    Twilio
        TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, TWILIO_TO_NUMBER
    Discord
        DISCORD_WEBHOOK_URL
    Telegram
        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    """

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _require_env(name: str) -> str:
        value = os.environ.get(name)
        if not value:
            raise NotificationError(
                f"Missing required environment variable: {name!r}. "
                "Set it in your .env file or CI/CD secrets."
            )
        return value

    # ------------------------------------------------------------------
    # SMS via Twilio
    # ------------------------------------------------------------------

    def send_sms(self, payload: AlertPayload) -> None:
        """
        Send an SMS alert via the Twilio REST API.

        Required env vars
        -----------------
        TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, TWILIO_TO_NUMBER
        """
        try:
            account_sid = self._require_env("TWILIO_ACCOUNT_SID")
            auth_token  = self._require_env("TWILIO_AUTH_TOKEN")
            from_number = self._require_env("TWILIO_FROM_NUMBER")
            to_number   = self._require_env("TWILIO_TO_NUMBER")
        except NotificationError:
            logger.error("Twilio credentials incomplete — skipping SMS.")
            raise

        # Lazy import: only needed when SMS is actually used
        try:
            from twilio.rest import Client as TwilioClient          # type: ignore
            from twilio.base.exceptions import TwilioRestException  # type: ignore
        except ImportError as exc:
            raise NotificationError(
                "The 'twilio' package is not installed. Run: pip install twilio"
            ) from exc

        message_body = _build_message(payload)

        try:
            client = TwilioClient(account_sid, auth_token)
            message = client.messages.create(
                body=message_body,
                from_=from_number,
                to=to_number,
            )
            logger.info("SMS sent — Twilio SID: %s", message.sid)
        except TwilioRestException as exc:
            raise NotificationError(f"Twilio API error: {exc}") from exc
        except Exception as exc:
            raise NotificationError(f"Unexpected error sending SMS: {exc}") from exc

    # ------------------------------------------------------------------
    # Discord Webhook
    # ------------------------------------------------------------------

    def send_discord(self, payload: AlertPayload, *, timeout: int = 10) -> None:
        """
        Post a rich embed to a Discord channel via Webhook.

        Required env vars
        -----------------
        DISCORD_WEBHOOK_URL
        """
        webhook_url = self._require_env("DISCORD_WEBHOOK_URL")

        body = _build_discord_embed(payload)

        try:
            response = requests.post(webhook_url, json=body, timeout=timeout)
            response.raise_for_status()
            logger.info("Discord notification delivered (HTTP %d).", response.status_code)
        except requests.exceptions.HTTPError as exc:
            raise NotificationError(
                f"Discord webhook HTTP error {exc.response.status_code}: "
                f"{exc.response.text}"
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise NotificationError(f"Cannot reach Discord: {exc}") from exc
        except requests.exceptions.Timeout:
            raise NotificationError(
                f"Discord webhook timed out after {timeout}s."
            )
        except Exception as exc:
            raise NotificationError(f"Unexpected Discord error: {exc}") from exc

    # ------------------------------------------------------------------
    # Telegram Bot API
    # ------------------------------------------------------------------

    def send_telegram(self, payload: AlertPayload, *, timeout: int = 10) -> None:
        """
        Send a Markdown-formatted message via a Telegram Bot.

        Required env vars
        -----------------
        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
        """
        bot_token = self._require_env("TELEGRAM_BOT_TOKEN")
        chat_id   = self._require_env("TELEGRAM_CHAT_ID")

        text = _build_message(payload)
        api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        body = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }

        try:
            response = requests.post(api_url, json=body, timeout=timeout)
            response.raise_for_status()
            result = response.json()
            if not result.get("ok"):
                raise NotificationError(
                    f"Telegram API returned ok=false: {result.get('description')}"
                )
            logger.info(
                "Telegram message sent — message_id=%s",
                result.get("result", {}).get("message_id"),
            )
        except requests.exceptions.HTTPError as exc:
            raise NotificationError(
                f"Telegram API HTTP error {exc.response.status_code}: "
                f"{exc.response.text}"
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise NotificationError(f"Cannot reach Telegram: {exc}") from exc
        except requests.exceptions.Timeout:
            raise NotificationError(
                f"Telegram API timed out after {timeout}s."
            )
        except NotificationError:
            raise
        except Exception as exc:
            raise NotificationError(f"Unexpected Telegram error: {exc}") from exc

    # ------------------------------------------------------------------
    # Convenience: broadcast to all configured channels
    # ------------------------------------------------------------------

    def broadcast(self, payload: AlertPayload) -> dict[str, bool]:
        """
        Attempt delivery on every configured channel.

        Returns
        -------
        dict[str, bool]
            ``{"sms": True, "discord": False, "telegram": True}`` — one key
            per channel, ``True`` meaning success.
        """
        results: dict[str, bool] = {}

        channels = {
            "sms": (
                self.send_sms,
                {"TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN",
                 "TWILIO_FROM_NUMBER", "TWILIO_TO_NUMBER"},
            ),
            "discord": (self.send_discord, {"DISCORD_WEBHOOK_URL"}),
            "telegram": (
                self.send_telegram,
                {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"},
            ),
        }

        for channel_name, (send_fn, required_vars) in channels.items():
            # Skip channels whose credentials are entirely absent
            if not any(os.environ.get(v) for v in required_vars):
                logger.debug("Channel %r not configured — skipping.", channel_name)
                continue

            try:
                send_fn(payload)
                results[channel_name] = True
            except NotificationError as exc:
                logger.error("Channel %r failed: %s", channel_name, exc)
                results[channel_name] = False

        if not results:
            logger.warning(
                "No notification channels are configured. "
                "Set at least one set of credentials in your .env file."
            )

        return results
