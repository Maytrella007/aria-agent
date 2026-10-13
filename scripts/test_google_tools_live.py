#!/usr/bin/env python3
"""
ARIA - Live Test for Google Tools (Gmail, Calendar, Drive)
==========================================================

This script:
1. Sets up Google OAuth credentials
2. Opens browser for you to authorize
3. Tests all 3 Google tools with real API calls
4. Uses DeepSeek LLM to run the associated skills

Usage:
    python3 scripts/test_google_tools_live.py

Prerequisites:
    - Google Cloud project with Gmail, Calendar, Drive APIs enabled
    - OAuth consent screen configured with your email as test user
    - Internet connection
"""

import os
import sys
import json
import time
import traceback

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

# ============================================================================
# Configuration
# ============================================================================

GOOGLE_CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
DEEPSEEK_API_KEY = os.environ["DEEPSEEK_API_KEY"]

# Set env vars before importing ARIA modules
os.environ["GOOGLE_CLIENT_ID"] = GOOGLE_CLIENT_ID
os.environ["GOOGLE_CLIENT_SECRET"] = GOOGLE_CLIENT_SECRET
os.environ["DEEPSEEK_API_KEY"] = DEEPSEEK_API_KEY

# ============================================================================
# Imports (after env setup)
# ============================================================================

from core.infra.auth_manager import AuthManager
from core.tools.gmail_tool import GmailTool
from core.tools.calendar_tool import GoogleCalendarTool
from core.tools.drive_tool import GoogleDriveTool

# ============================================================================
# Helpers
# ============================================================================

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
SKIP = "\033[93mSKIP\033[0m"
INFO = "\033[96mINFO\033[0m"

results = {"pass": 0, "fail": 0, "skip": 0}


def header(text):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}")


def test(name, func):
    """Run a test and report result."""
    print(f"\n  [{INFO}] {name}...")
    try:
        result = func()
        if result and result.success:
            print(f"  [{PASS}] {name}")
            if result.output:
                # Show first 3 lines of output
                lines = result.output.strip().split("\n")
                for line in lines[:3]:
                    print(f"         {line[:100]}")
                if len(lines) > 3:
                    print(f"         ... ({len(lines)} lines total)")
            results["pass"] += 1
            return result
        else:
            error = result.error if result else "No result returned"
            print(f"  [{FAIL}] {name}: {error}")
            results["fail"] += 1
            return result
    except Exception as e:
        print(f"  [{FAIL}] {name}: {e}")
        traceback.print_exc()
        results["fail"] += 1
        return None


# ============================================================================
# Step 1: OAuth Setup
# ============================================================================

def setup_oauth():
    header("Step 1: Google OAuth Authentication")

    # Save client credentials to file (like 'auth google setup' does)
    auth_dir = os.path.join(PROJECT_ROOT, "data", "auth")
    os.makedirs(auth_dir, exist_ok=True)
    client_path = os.path.join(auth_dir, "google_oauth_client.json")
    with open(client_path, "w") as f:
        json.dump({
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
        }, f)
    print(f"  [{PASS}] Client credentials saved to {client_path}")

    # Initialize AuthManager
    auth = AuthManager()

    # Check if we already have valid tokens
    token = auth.get_credential("google")
    if token:
        print(f"  [{PASS}] Already authenticated (token found)")
        return auth

    # Need to login
    print(f"\n  [{INFO}] Opening browser for Google OAuth...")
    print(f"  [{INFO}] Please authorize access to Gmail, Calendar, and Drive")
    print(f"  [{INFO}] Waiting for authorization...\n")

    success = auth.login_oauth(provider="google", method="browser")
    if success:
        print(f"\n  [{PASS}] OAuth login successful!")
        token = auth.get_credential("google")
        if token:
            print(f"  [{PASS}] Access token obtained ({len(token)} chars)")
        return auth
    else:
        print(f"\n  [{FAIL}] OAuth login failed!")
        print(f"  [{INFO}] Make sure you:")
        print(f"         1. Enabled Gmail, Calendar, Drive APIs in Google Cloud Console")
        print(f"         2. Added your email as test user in OAuth consent screen")
        print(f"         3. Authorized all requested permissions in the browser")
        return None


# ============================================================================
# Step 2: Test Tools Directly
# ============================================================================

def test_tools(auth):
    header("Step 2: Direct Tool Tests")

    context = {"auth_manager": auth, "data_dir": os.path.join(PROJECT_ROOT, "data")}

    # --- Gmail ---
    print(f"\n  --- Gmail Tool ---")
    gmail = GmailTool(context=context)

    # Test: list labels
    test("Gmail: list labels", lambda: gmail.execute(action="labels"))

    # Test: search emails
    r = test("Gmail: search recent emails", lambda: gmail.execute(action="search", query="newer_than:7d", max_results=5))

    # Test: read first email (if search returned results)
    if r and r.success and r.data and r.data.get("messages"):
        msg_id = r.data["messages"][0].get("id") or r.data["messages"][0].get("message_id")
        if msg_id:
            test("Gmail: read email", lambda: gmail.execute(action="read", message_id=msg_id))

    # --- Calendar ---
    print(f"\n  --- Google Calendar Tool ---")
    calendar = GoogleCalendarTool(context=context)

    # Test: list calendars
    test("Calendar: list calendars", lambda: calendar.execute(action="calendars"))

    # Test: list upcoming events
    test("Calendar: list events (next 30 days)", lambda: calendar.execute(action="list", days_ahead=30))

    # Test: create event
    from datetime import datetime, timedelta
    tomorrow = datetime.now() + timedelta(days=1)
    start = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")
    end = tomorrow.replace(hour=11, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")

    r = test("Calendar: create test event", lambda: calendar.execute(
        action="create",
        summary="ARIA Test Event (delete me)",
        start=start,
        end=end,
        description="Automated test event created by ARIA test script",
    ))

    # Test: delete the event we just created
    if r and r.success and r.data and r.data.get("event_id"):
        event_id = r.data["event_id"]
        test("Calendar: delete test event", lambda: calendar.execute(action="delete", event_id=event_id))

    # --- Drive ---
    print(f"\n  --- Google Drive Tool ---")
    drive = GoogleDriveTool(context=context)

    # Test: search files
    test("Drive: search files", lambda: drive.execute(action="search", query="", max_results=5))

    # Test: list root folder
    test("Drive: list root folder", lambda: drive.execute(action="list", max_results=5))


# ============================================================================
# Step 3: Test Skills with DeepSeek LLM
# ============================================================================

def test_skills(auth):
    header("Step 3: Skill Tests (with DeepSeek LLM)")

    try:
        from core.skills.base import SkillContext
        from core.skills.gmail_assistant import GmailAssistantSkill
        from core.skills.inbox_triage import InboxTriageSkill
        from core.skills.meeting_prep import MeetingPrepSkill
        from core.tools.registry import ToolRegistry
        from core.llm.llm_providers import LLMProvider
    except ImportError as e:
        print(f"  [{SKIP}] Could not import skills: {e}")
        results["skip"] += 3
        return

    # Build ToolRegistry with the 3 Google tools
    tool_reg = ToolRegistry()
    tool_context = {"auth_manager": auth, "data_dir": os.path.join(PROJECT_ROOT, "data")}
    tool_reg.register(GmailTool(context=tool_context))
    tool_reg.register(GoogleCalendarTool(context=tool_context))
    tool_reg.register(GoogleDriveTool(context=tool_context))

    # Create DeepSeek LLM
    print(f"  [{INFO}] Initializing DeepSeek LLM...")
    try:
        llm = LLMProvider.create("deepseek", api_key=DEEPSEEK_API_KEY)
        print(f"  [{PASS}] DeepSeek LLM ready")
    except Exception as e:
        print(f"  [{FAIL}] Could not create DeepSeek LLM: {e}")
        results["skip"] += 3
        return

    # Build SkillContext
    ctx = SkillContext(tools=tool_reg, llm=llm)

    # Gmail Assistant Skill
    print(f"\n  --- GmailAssistantSkill ---")
    try:
        skill = GmailAssistantSkill()
        r = test("Skill: Gmail check inbox", lambda: skill.execute(
            query="check my inbox for recent emails",
            ctx=ctx,
        ))
    except Exception as e:
        print(f"  [{FAIL}] GmailAssistantSkill: {e}")
        results["fail"] += 1

    # Inbox Triage Skill
    print(f"\n  --- InboxTriageSkill ---")
    try:
        skill = InboxTriageSkill()
        r = test("Skill: Triage unread emails", lambda: skill.execute(
            query="triage my unread emails",
            ctx=ctx,
        ))
    except Exception as e:
        print(f"  [{FAIL}] InboxTriageSkill: {e}")
        results["fail"] += 1

    # Meeting Prep Skill
    print(f"\n  --- MeetingPrepSkill ---")
    try:
        skill = MeetingPrepSkill()
        r = test("Skill: Prepare for upcoming meetings", lambda: skill.execute(
            query="prepare briefing for my next meeting",
            ctx=ctx,
        ))
    except Exception as e:
        print(f"  [{FAIL}] MeetingPrepSkill: {e}")
        results["fail"] += 1


# ============================================================================
# Main
# ============================================================================

def main():
    print("\n" + "="*60)
    print("  ARIA - Google Tools Live Test")
    print("="*60)

    # Step 1: OAuth
    auth = setup_oauth()
    if not auth:
        print(f"\n  [{FAIL}] Cannot continue without authentication")
        sys.exit(1)

    # Step 2: Direct tool tests
    test_tools(auth)

    # Step 3: Skill tests (with LLM)
    print(f"\n  [{INFO}] Run skill tests with DeepSeek LLM? (y/n): ", end="")
    try:
        answer = input().strip().lower()
    except EOFError:
        answer = "y"

    if answer in ("y", "yes", ""):
        test_skills(auth)
    else:
        print(f"  [{SKIP}] Skipping skill tests")
        results["skip"] += 3

    # Summary
    header("Results")
    total = results["pass"] + results["fail"] + results["skip"]
    print(f"\n  Total:   {total}")
    print(f"  Passed:  {results['pass']}")
    print(f"  Failed:  {results['fail']}")
    print(f"  Skipped: {results['skip']}")
    print()

    if results["fail"] == 0:
        print(f"  [{PASS}] All Google tools working!")
    else:
        print(f"  [{FAIL}] {results['fail']} test(s) failed — review output above")

    sys.exit(0 if results["fail"] == 0 else 1)


if __name__ == "__main__":
    main()
