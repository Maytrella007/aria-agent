# Telegram Setup

## Step 1: Create the Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Choose a name (for example: `ARIA Bot`)
4. Choose a username (for example: `aria_ai_bot`)
5. BotFather will return a **token** like: `7123456789:AAH...`

## Step 2: Configure ARIA

Add the token to your `.env`:

```
TELEGRAM_BOT_TOKEN=7123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxx
```

Enable Telegram in `config.yaml`:

```yaml
telegram:
  enabled: true
  bot_token: "${TELEGRAM_BOT_TOKEN}"
  allowed_users: []     # empty = allow everyone
  log_messages: true
```

## Step 3: Restrict Access (Optional)

If you want only specific users to talk to ARIA:

1. Message `@userinfobot` in Telegram to get your user ID
2. Add it to the list:

```yaml
telegram:
  allowed_users: [123456789, 987654321]
```

## Step 4: Run

```bash
python aria.py
```

If everything is correct, you will see `[Telegram bot active]` on startup.

## Step 5: Commands

**In Telegram:**
- `/start` — ARIA greeting
- `/status` — Bot status (uptime, message counts)
- `/help` — Help
- Any text — ARIA responds using its LLM and memory

**In the ARIA terminal:**
- `telegram` — Show bot status, metrics, and health check

## Step 6: Hardening

The bot includes automatic protections:

- **Rate limiting**: Max 20 messages per minute per user
- **Retry queue**: If a send fails, it retries up to 3 times with exponential backoff
- **Health check**: Verifies connection every 5 minutes
- **Metrics**: Average latency, daily messages, recent errors

## Troubleshooting

| Problem | Solution |
|---|---|
| Bot not responding | Verify that `telegram.enabled: true` and the token is correct |
| "Not authorized" | Your user ID is not in `allowed_users`. Leave it empty to allow everyone |
| Messages are cut off | Telegram limits messages to 4096 chars. ARIA splits long messages automatically |
| Bot disconnects | The health check should detect it. Restart ARIA |
