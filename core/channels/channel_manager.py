"""
ARIA Channel Manager
====================

Unified management layer for all messaging channels (Telegram, Discord, Slack).
Wraps the individual bot instances with a consistent API for the GUI and REST
endpoints.

The ChannelManager does NOT own the bot lifecycle from scratch — it receives
the already-instantiated (or None) bot references from the ARIA instance and
exposes read/control operations on them.

Usage:
    manager = ChannelManager(aria_instance)
    manager.list_channels()
    manager.start_channel("telegram")
"""

import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger("aria.channel_manager")


# Environment variable names for each channel's token(s).
_ENV_VARS = {
    "telegram": ["TELEGRAM_BOT_TOKEN"],
    "discord":  ["DISCORD_BOT_TOKEN"],
    "slack":    ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"],
}


class ChannelManager:
    """Unified facade over ARIA's messaging channels."""

    CHANNELS = {
        "telegram": {
            "class": "TelegramBot",
            "module": "telegram_bot",
            "kind": "bot",
            "description": "Telegram bot via long-polling",
        },
        "discord": {
            "class": "DiscordBot",
            "module": "discord_bot",
            "kind": "gateway",
            "description": "Discord bot via gateway websocket",
        },
        "slack": {
            "class": "SlackBot",
            "module": "slack_bot",
            "kind": "socket mode",
            "description": "Slack bot via Socket Mode (no public URL)",
        },
    }

    def __init__(self, aria_instance):
        """
        Args:
            aria_instance: The main ARIA object that holds .telegram, .discord,
                           .slack attributes (each may be None).
        """
        self._aria = aria_instance

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_bot(self, name: str):
        """Return the bot instance for *name*, or None."""
        return getattr(self._aria, name, None)

    def _env_configured(self, name: str) -> bool:
        """Check whether all required env vars for a channel are set."""
        env_keys = _ENV_VARS.get(name, [])
        return all(bool(os.environ.get(k, "").strip()) for k in env_keys)

    def _mask_token(self, raw: str) -> str:
        """Return a masked version showing only the last 4 characters."""
        if len(raw) <= 4:
            return "****"
        return "*" * (len(raw) - 4) + raw[-4:]

    def _channel_status(self, name: str) -> str:
        """Derive the current status string for a channel."""
        bot = self._get_bot(name)
        if bot is None:
            if not self._env_configured(name):
                return "unconfigured"
            return "stopped"  # configured but not instantiated
        if bot.is_running:
            return "running"
        return "stopped"

    def _channel_detail(self, name: str) -> Dict:
        """Build a detail dict for one channel."""
        meta = self.CHANNELS[name]
        bot = self._get_bot(name)
        status = self._channel_status(name)

        detail: Dict = {
            "name": name,
            "kind": meta["kind"],
            "description": meta["description"],
            "status": status,
            "env_vars": _ENV_VARS.get(name, []),
            "env_configured": self._env_configured(name),
        }

        # If a live bot exists, attach its real metrics from ChannelBase.stats()
        if bot is not None:
            detail["metrics"] = bot.stats()
        else:
            detail["metrics"] = None
            detail["metrics_note"] = (
                "No live bot instance — metrics unavailable. "
                "Start the channel to begin collecting metrics."
            )

        return detail

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_channels(self) -> List[Dict]:
        """List all channels with their current status and metrics."""
        return [self._channel_detail(name) for name in self.CHANNELS]

    def get_channel(self, name: str) -> Optional[Dict]:
        """Get detail for one channel, or None if unknown."""
        if name not in self.CHANNELS:
            return None
        return self._channel_detail(name)

    def get_dashboard(self) -> Dict:
        """Aggregated dashboard: messages today, active chats, health."""
        total_today = 0
        total_active_chats = 0
        channels_healthy = 0
        channels_running = 0
        channel_summaries = []

        for name in self.CHANNELS:
            bot = self._get_bot(name)
            status = self._channel_status(name)
            summary: Dict = {"name": name, "status": status}

            if bot is not None:
                stats = bot.stats()
                summary["messages_today"] = stats.get("messages_today", 0)
                summary["active_chats"] = stats.get("active_chats", 0)
                summary["healthy"] = stats.get("healthy", False)
                total_today += summary["messages_today"]
                total_active_chats += summary["active_chats"]
                if stats.get("healthy"):
                    channels_healthy += 1
                if status == "running":
                    channels_running += 1
            else:
                summary["messages_today"] = 0
                summary["active_chats"] = 0
                summary["healthy"] = None

            channel_summaries.append(summary)

        return {
            "timestamp": datetime.now().isoformat(),
            "total_messages_today": total_today,
            "total_active_chats": total_active_chats,
            "channels_running": channels_running,
            "channels_healthy": channels_healthy,
            "channels_total": len(self.CHANNELS),
            "channels": channel_summaries,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_channel(self, name: str) -> Dict:
        """Start a channel. The bot must already be instantiated by ARIA."""
        if name not in self.CHANNELS:
            return {"ok": False, "error": "unknown_channel", "detail": f"Unknown channel: {name}"}

        bot = self._get_bot(name)
        if bot is None:
            configured = self._env_configured(name)
            if not configured:
                return {
                    "ok": False,
                    "error": "unconfigured",
                    "detail": (
                        f"Channel '{name}' is not configured. "
                        f"Set the environment variable(s): {_ENV_VARS.get(name, [])} "
                        f"and restart ARIA."
                    ),
                }
            return {
                "ok": False,
                "error": "not_instantiated",
                "detail": (
                    f"Channel '{name}' has env vars set but the bot was not "
                    f"instantiated. Check config.yaml '{name}.enabled: true' "
                    f"and restart ARIA."
                ),
            }

        if bot.is_running:
            return {"ok": True, "detail": f"{name} is already running", "status": "running"}

        try:
            bot.start()
            logger.info(f"ChannelManager: started {name}")
            return {"ok": True, "status": "running"}
        except Exception as e:
            logger.error(f"ChannelManager: failed to start {name}: {e}")
            return {"ok": False, "error": "start_failed", "detail": str(e)}

    def stop_channel(self, name: str) -> Dict:
        """Stop a running channel."""
        if name not in self.CHANNELS:
            return {"ok": False, "error": "unknown_channel", "detail": f"Unknown channel: {name}"}

        bot = self._get_bot(name)
        if bot is None:
            return {"ok": False, "error": "not_instantiated", "detail": f"No bot instance for '{name}'"}

        if not bot.is_running:
            return {"ok": True, "detail": f"{name} is already stopped", "status": "stopped"}

        try:
            bot.stop()
            logger.info(f"ChannelManager: stopped {name}")
            return {"ok": True, "status": "stopped"}
        except Exception as e:
            logger.error(f"ChannelManager: failed to stop {name}: {e}")
            return {"ok": False, "error": "stop_failed", "detail": str(e)}

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def update_config(self, name: str, config: Dict) -> Dict:
        """
        Update runtime configuration for a channel.

        Currently limited to attributes that the bots expose (e.g.
        allowed_users, log_messages). Does NOT hot-reload tokens —
        a restart is needed for token changes.
        """
        if name not in self.CHANNELS:
            return {"ok": False, "error": "unknown_channel", "detail": f"Unknown channel: {name}"}

        bot = self._get_bot(name)
        if bot is None:
            return {"ok": False, "error": "not_instantiated", "detail": f"No bot instance for '{name}'"}

        applied = {}
        for key, value in config.items():
            if hasattr(bot, key) and not key.startswith("_"):
                setattr(bot, key, value)
                applied[key] = value
                logger.info(f"ChannelManager: {name}.{key} = {value!r}")

        ignored = [k for k in config if k not in applied]

        return {
            "ok": True,
            "applied": applied,
            "ignored": ignored,
            "note": "Token changes require a channel restart." if "token" in config else None,
        }

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def reveal_token(self, name: str) -> Dict:
        """
        Reveal the token(s) for a channel (masked — last 4 chars visible).

        POST-only endpoint: secrets must never appear in GET query strings
        or browser history.
        """
        if name not in self.CHANNELS:
            return {"ok": False, "error": "unknown_channel", "detail": f"Unknown channel: {name}"}

        env_keys = _ENV_VARS.get(name, [])
        tokens = {}
        for key in env_keys:
            raw = os.environ.get(key, "")
            if raw:
                tokens[key] = self._mask_token(raw)
            else:
                tokens[key] = None  # not set

        return {"ok": True, "channel": name, "tokens": tokens}

    def rotate_token(self, name: str) -> Dict:
        """
        Rotate a channel token.

        Token rotation requires generating a new token through the provider's
        own dashboard (BotFather for Telegram, Developer Portal for Discord,
        api.slack.com for Slack). This cannot be automated safely from ARIA.
        """
        if name not in self.CHANNELS:
            return {"ok": False, "error": "unknown_channel", "detail": f"Unknown channel: {name}"}

        providers = {
            "telegram": "Telegram @BotFather (/revoke + /newbot)",
            "discord": "Discord Developer Portal (Bot > Reset Token)",
            "slack": "api.slack.com (App Settings > Install App)",
        }

        return {
            "ok": False,
            "error": "not_implemented",
            "detail": (
                f"Token rotation for '{name}' must be done manually via the "
                f"provider dashboard: {providers.get(name, 'unknown provider')}. "
                f"After obtaining the new token, update the environment variable(s) "
                f"{_ENV_VARS.get(name, [])} and restart the channel."
            ),
        }
