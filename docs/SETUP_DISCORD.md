# Discord Setup

This guide configures the real-time Discord channel for ARIA.

## Prerequisites

- A Discord application and bot token from the Discord Developer Portal
- Permission to add the bot to your server

## Step 1: Create the Bot

1. Go to https://discord.com/developers/applications
2. Create a new application
3. Open the **Bot** section
4. Create a bot user
5. Copy the bot token

## Step 2: Enable Privileged Intents If Needed

Depending on your server setup, enable the intents needed for message handling.

At minimum, ARIA's Discord bot expects normal message access in channels where it is allowed to run.

## Step 3: Configure ARIA

Set the token:

```bash
export DISCORD_BOT_TOKEN=your-discord-bot-token
```

Enable Discord in `config.yaml`:

```yaml
discord:
  enabled: true
  bot_token: "${DISCORD_BOT_TOKEN}"
  allowed_guild_ids: []
  allowed_channel_ids: []
  log_messages: true
```

## Step 4: Invite the Bot

Use the OAuth URL from the Developer Portal to invite the bot to your server.

If you want to limit where ARIA runs, set:

- `allowed_guild_ids`
- `allowed_channel_ids`

## Step 5: Run ARIA

```bash
python3 aria.py
```

## Notes

- Discord is a real-time channel, not just a tool integration.
- Slack and Discord are documented separately because their runtime requirements are different.
