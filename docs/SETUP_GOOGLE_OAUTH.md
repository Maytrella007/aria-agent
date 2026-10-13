# Google OAuth Setup

This guide configures ARIA to access Gmail, Google Calendar, and Google Drive on your behalf.

## Prerequisites

- A Google account
- Access to [Google Cloud Console](https://console.cloud.google.com/)

## Step 1: Create a Google Cloud Project

1. Go to https://console.cloud.google.com/
2. Click the project selector (top bar) > **New Project**
3. Name it (e.g. "ARIA") and click **Create**
4. Make sure the new project is selected

## Step 2: Enable APIs

Go to **APIs & Services > Library** and enable these three APIs:

- **Gmail API** — search, read, send emails
- **Google Calendar API** — list, create, update events
- **Google Drive API** — search, read, download files

## Step 3: Configure OAuth Consent Screen

1. Go to **APIs & Services > OAuth consent screen**
2. Select **External** user type, click **Create**
3. Fill in:
   - App name: `ARIA`
   - User support email: your email
   - Developer contact: your email
4. Click **Save and Continue**
5. **Scopes**: click **Add or Remove Scopes**, then add:
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/gmail.send`
   - `https://www.googleapis.com/auth/drive.readonly`
   - `https://www.googleapis.com/auth/calendar`
6. Click **Save and Continue**
7. **Test users**: click **Add Users**, enter your Gmail address
8. Click **Save and Continue**

> **Note:** In "Testing" mode, only the test users you add can authorize the app. This is fine for personal use.

## Step 4: Create OAuth Credentials

1. Go to **APIs & Services > Credentials**
2. Click **Create Credentials > OAuth 2.0 Client ID**
3. Application type: **Desktop app**
4. Name: `ARIA`
5. Click **Create**
6. Copy the **Client ID** and **Client Secret**

## Step 5: Configure ARIA

```bash
python3 aria.py
```

Inside ARIA:

```
auth google setup <YOUR_CLIENT_ID> <YOUR_CLIENT_SECRET>
```

This saves credentials to `data/auth/google_oauth_client.json`.

## Step 6: Login

```
auth login google
```

This opens your browser. Sign in with Google, authorize the requested scopes, and ARIA stores the tokens in `data/auth/oauth_tokens.yaml` with a refresh token (`access_type=offline`).

## Step 7: Verify

```
auth status
```

You should see:

```
google_oauth_1: [oauth] google — OK (expires Xm)
```

## What You Can Do Now

- **Gmail**: `check my inbox`, `search emails from GitHub`, `triage my inbox`
- **Calendar**: `what meetings do I have this week?`, `prepare for my next meeting`
- **Drive**: `search my drive for project docs`

## Token Refresh

Tokens auto-refresh before expiry. If they expire (e.g. after revoking access), run:

```
auth login google
```

To manually force a refresh:

```
auth refresh google
```

## Revoking Access

```
auth revoke google
```

This revokes the token with Google and deletes local credentials.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Access blocked" in browser | Add your email as a test user in OAuth consent screen |
| "redirect_uri_mismatch" | Make sure you selected "Desktop app" as application type |
| Token expired immediately | Check your system clock is accurate |
| "insufficient scopes" | Re-run `auth login google` — scopes may have changed |
| Port 8900 in use | Kill the process using it, then retry `auth login google` |
