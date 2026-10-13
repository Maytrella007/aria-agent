# Slack Setup

This guide covers two Slack integrations:

1. `SlackTool` / `slack_assistant`
2. The real-time Slack channel bot (`core/channels/slack_bot.py`)

The first only needs a bot token.
The second uses Socket Mode and needs both a bot token and an app token.

## Prerequisites

- Admin access to a Slack workspace (or permission to install apps)

## Step 1: Create a Slack App

1. Go to https://api.slack.com/apps
2. Click **Create New App** > **From scratch**
3. App Name: `ARIA`
4. Pick your workspace
5. Click **Create App**

## Step 2: Configure Bot Permissions

1. In the left sidebar, go to **OAuth & Permissions**
2. Scroll to **Bot Token Scopes** and add:

| Scope | Purpose |
|-------|---------|
| `channels:read` | List public channels |
| `channels:history` | Read messages in public channels |
| `chat:write` | Send messages |
| `reactions:write` | Add emoji reactions |
| `pins:write` | Pin messages |

If you want the Slack channel bot, also enable Socket Mode in your Slack app.

## Step 3: Install to Workspace

1. Go to **OAuth & Permissions** (or **Install App** in sidebar)
2. Click **Install to Workspace**
3. Authorize the requested permissions
4. Copy the **Bot User OAuth Token** (starts with `xoxb-`)

## Step 3.5: Create an App-Level Token for Socket Mode

Required for the real-time Slack channel bot.

1. Open **Basic Information** in the Slack app settings
2. Under **App-Level Tokens**, create a token with `connections:write`
3. Copy the token (starts with `xapp-`)

## Step 4: Configure ARIA

### Option A: Slack tool only

Set the environment variable before starting ARIA:

```bash
export SLACK_BOT_TOKEN=xoxb-your-token-here
python3 aria.py
```

Or add it to your shell profile (`~/.bashrc`, `~/.zshrc`):

```bash
echo 'export SLACK_BOT_TOKEN=xoxb-your-token-here' >> ~/.bashrc
source ~/.bashrc
```

This is enough for:

- `SlackTool`
- `slack_assistant`

### Option B: Full Slack channel bot

Set both environment variables:

```bash
export SLACK_BOT_TOKEN=xoxb-your-token-here
export SLACK_APP_TOKEN=xapp-your-token-here
```

And enable Slack in `config.yaml`:

```yaml
slack:
  enabled: true
  bot_token: "${SLACK_BOT_TOKEN}"
  app_token: "${SLACK_APP_TOKEN}"
  allowed_channel_ids: []
  log_messages: true
```

## Step 5: Invite the Bot to Channels

The bot can only read channels it's a member of. In Slack:

```
/invite @ARIA
```

Or mention `@ARIA` in the channel to trigger an invitation prompt.

## Step 6: Verify

Inside ARIA:

```
read slack channel C0123456789
```

Replace `C0123456789` with your actual channel ID. To find a channel ID: right-click the channel name in Slack > **View channel details** > scroll to the bottom.

## What You Can Do Now

- **Read**: `summarize the engineering channel`
- **Send**: `send "Deploy complete" to C0123456789`
- **React**: via the `slack` tool with action `react`
- **Pin**: via the `slack` tool with action `pin`

If the channel bot is enabled, Slack can also be used as a live conversation channel for ARIA.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "not_in_channel" error | Invite the bot to the channel with `/invite @ARIA` |
| "invalid_auth" error | Check that `SLACK_BOT_TOKEN` is set correctly |
| Socket Mode fails to connect | Verify `SLACK_APP_TOKEN` exists and starts with `xapp-` |
| "missing_scope" error | Add the required scope in Slack App settings and reinstall |
| Can't find channel ID | Right-click channel > View channel details > ID at bottom |
