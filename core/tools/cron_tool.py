"""
ARIA - Cron Tool
=================

Schedule and manage recurring tasks.
Uses the schedule library for job management.
Inspired by OpenClaw's cron_tool (schedule, list, remove, run).

Jobs persist in memory during the session and execute callbacks
through ARIA's existing systems.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.cron")

try:
    import schedule
    SCHEDULE_AVAILABLE = True
except ImportError:
    SCHEDULE_AVAILABLE = False


# =============================================================================
# JOB STORE
# =============================================================================

class JobStore:
    """Persistent job storage and scheduler."""

    def __init__(self, data_dir: str = "data"):
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._scheduler = schedule.Scheduler() if SCHEDULE_AVAILABLE else None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._callbacks: Dict[str, Any] = {}
        self._store_path = os.path.join(data_dir, "cron_jobs.json")
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        """Load jobs from disk."""
        if os.path.exists(self._store_path):
            try:
                with open(self._store_path, "r", encoding="utf-8") as f:
                    self._jobs = json.load(f)
            except Exception:
                self._jobs = {}

    def _save(self):
        """Save jobs to disk."""
        try:
            os.makedirs(os.path.dirname(self._store_path), exist_ok=True)
            with open(self._store_path, "w", encoding="utf-8") as f:
                json.dump(self._jobs, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save cron jobs: {e}")

    def add(self, name: str, schedule_expr: str, action: str, enabled: bool = True) -> bool:
        """Add a job."""
        with self._lock:
            self._jobs[name] = {
                "name": name,
                "schedule": schedule_expr,
                "action": action,
                "enabled": enabled,
                "created_at": datetime.now().isoformat(),
                "last_run": None,
                "run_count": 0,
            }
            self._save()

            if self._scheduler and enabled:
                self._register_job(name, schedule_expr, action)

            return True

    def remove(self, name: str) -> bool:
        """Remove a job."""
        with self._lock:
            if name not in self._jobs:
                return False
            del self._jobs[name]
            if name in self._callbacks:
                del self._callbacks[name]
            self._rebuild_scheduler()
            self._save()
            return True

    def list_jobs(self) -> List[Dict[str, Any]]:
        """List all jobs."""
        return list(self._jobs.values())

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a specific job."""
        return self._jobs.get(name)

    def toggle(self, name: str, enabled: bool) -> bool:
        """Enable or disable a job."""
        with self._lock:
            if name not in self._jobs:
                return False
            self._jobs[name]["enabled"] = enabled
            self._rebuild_scheduler()
            self._save()
            return True

    def run_now(self, name: str) -> Optional[str]:
        """Run a job immediately. Returns the action string."""
        with self._lock:
            job = self._jobs.get(name)
            if not job:
                return None
            job["last_run"] = datetime.now().isoformat()
            job["run_count"] = job.get("run_count", 0) + 1
            self._save()
            return job["action"]

    # -------------------------------------------------------------------------
    # Scheduler management
    # -------------------------------------------------------------------------

    def start(self, callback=None):
        """Start the scheduler thread."""
        if not SCHEDULE_AVAILABLE:
            logger.warning("schedule library not available")
            return
        if self._running:
            return

        self._default_callback = callback
        self._rebuild_scheduler()
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name="aria-cron",
            daemon=True,
        )
        self._thread.start()
        logger.info("Cron scheduler started")

    def stop(self):
        """Stop the scheduler thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _run_loop(self):
        """Background scheduler loop."""
        while self._running:
            if self._scheduler:
                self._scheduler.run_pending()
            time.sleep(1)

    def _rebuild_scheduler(self):
        """Rebuild all scheduled jobs."""
        if not self._scheduler:
            return
        self._scheduler.clear()
        for name, job in self._jobs.items():
            if job.get("enabled", True):
                self._register_job(name, job["schedule"], job["action"])

    def _register_job(self, name: str, schedule_expr: str, action: str):
        """Register a single job with the scheduler."""
        if not self._scheduler:
            return

        try:
            # Parse schedule expression
            # Formats: "every 5 minutes", "every 1 hour", "every day at 09:00",
            #          "every monday at 10:00"
            expr = schedule_expr.lower().strip()

            if "minute" in expr:
                mins = self._extract_number(expr, 1)
                job = self._scheduler.every(mins).minutes
            elif "hour" in expr:
                hrs = self._extract_number(expr, 1)
                job = self._scheduler.every(hrs).hours
            elif "day" in expr:
                job = self._scheduler.every().day
                at_time = self._extract_time(expr)
                if at_time:
                    job = job.at(at_time)
            elif "monday" in expr:
                job = self._scheduler.every().monday
                at_time = self._extract_time(expr)
                if at_time:
                    job = job.at(at_time)
            elif "tuesday" in expr:
                job = self._scheduler.every().tuesday
                at_time = self._extract_time(expr)
                if at_time:
                    job = job.at(at_time)
            elif "wednesday" in expr:
                job = self._scheduler.every().wednesday
                at_time = self._extract_time(expr)
                if at_time:
                    job = job.at(at_time)
            elif "thursday" in expr:
                job = self._scheduler.every().thursday
                at_time = self._extract_time(expr)
                if at_time:
                    job = job.at(at_time)
            elif "friday" in expr:
                job = self._scheduler.every().friday
                at_time = self._extract_time(expr)
                if at_time:
                    job = job.at(at_time)
            elif "saturday" in expr:
                job = self._scheduler.every().saturday
                at_time = self._extract_time(expr)
                if at_time:
                    job = job.at(at_time)
            elif "sunday" in expr:
                job = self._scheduler.every().sunday
                at_time = self._extract_time(expr)
                if at_time:
                    job = job.at(at_time)
            elif "second" in expr:
                secs = self._extract_number(expr, 30)
                job = self._scheduler.every(secs).seconds
            else:
                logger.warning(f"Unknown schedule format: {schedule_expr}")
                return

            def make_callback(n, a):
                def cb():
                    self._on_job_run(n, a)
                return cb

            job.do(make_callback(name, action))
            logger.debug(f"Registered cron job: {name} -> {schedule_expr}")

        except Exception as e:
            logger.error(f"Failed to register job {name}: {e}")

    def _on_job_run(self, name: str, action: str):
        """Called when a scheduled job fires."""
        with self._lock:
            if name in self._jobs:
                self._jobs[name]["last_run"] = datetime.now().isoformat()
                self._jobs[name]["run_count"] = self._jobs[name].get("run_count", 0) + 1
                self._save()

        logger.info(f"Cron job fired: {name} -> {action}")

        if self._default_callback:
            try:
                self._default_callback(name, action)
            except Exception as e:
                logger.error(f"Cron callback error for {name}: {e}")

    @staticmethod
    def _extract_number(text: str, default: int = 1) -> int:
        import re
        match = re.search(r"(\d+)", text)
        return int(match.group(1)) if match else default

    @staticmethod
    def _extract_time(text: str) -> Optional[str]:
        import re
        match = re.search(r"(\d{1,2}:\d{2})", text)
        return match.group(1) if match else None


# =============================================================================
# Singleton job store
# =============================================================================

_job_store: Optional[JobStore] = None


def get_job_store(data_dir: str = "data") -> JobStore:
    global _job_store
    if _job_store is None:
        _job_store = JobStore(data_dir)
    return _job_store


# =============================================================================
# CRON TOOL
# =============================================================================

class CronTool(ToolBase):
    """Schedule and manage recurring tasks."""

    name = "cron"
    description = (
        "Schedule recurring tasks, reminders, and automations. "
        "Actions: add, remove, list, enable, disable, run. "
        "Schedule formats: 'every 5 minutes', 'every day at 09:00', 'every monday at 10:00'."
    )
    parameters = [
        ToolParam(
            name="action",
            type="string",
            description="Action: add, remove, list, enable, disable, run",
            required=True,
            enum=["add", "remove", "list", "enable", "disable", "run"],
        ),
        ToolParam(
            name="name",
            type="string",
            description="Job name (required for add/remove/enable/disable/run)",
            required=False,
        ),
        ToolParam(
            name="schedule",
            type="string",
            description="Schedule expression (for add). E.g. 'every 5 minutes', 'every day at 09:00'",
            required=False,
        ),
        ToolParam(
            name="task",
            type="string",
            description="Task description or command to execute (for add)",
            required=False,
        ),
    ]

    def __init__(self, context=None):
        super().__init__(context)
        data_dir = self.context.get("data_dir", "data")
        self._store = get_job_store(data_dir)

    def _execute(self, **kwargs) -> ToolResult:
        if not SCHEDULE_AVAILABLE:
            return ToolResult(success=False, error="schedule library not installed. Run: pip install schedule")

        action = kwargs["action"]

        if action == "list":
            return self._list()
        elif action == "add":
            return self._add(kwargs)
        elif action == "remove":
            return self._remove(kwargs)
        elif action == "enable":
            return self._toggle(kwargs, True)
        elif action == "disable":
            return self._toggle(kwargs, False)
        elif action == "run":
            return self._run(kwargs)

        return ToolResult(success=False, error=f"Unknown action: {action}")

    def _list(self) -> ToolResult:
        jobs = self._store.list_jobs()
        if not jobs:
            return ToolResult(success=True, output="No scheduled jobs.", data={"jobs": []})

        lines = ["Scheduled jobs:\n"]
        for j in jobs:
            status = "ON" if j.get("enabled", True) else "OFF"
            last = j.get("last_run", "never")
            if last and last != "never":
                last = last[:19]  # Trim microseconds
            lines.append(f"  [{status}] {j['name']}")
            lines.append(f"       Schedule: {j['schedule']}")
            lines.append(f"       Action: {j['action']}")
            lines.append(f"       Runs: {j.get('run_count', 0)} | Last: {last}")
            lines.append("")

        return ToolResult(success=True, output="\n".join(lines), data={"jobs": jobs})

    def _add(self, kwargs) -> ToolResult:
        name = kwargs.get("name")
        sched = kwargs.get("schedule")
        task = kwargs.get("task")

        if not name:
            return ToolResult(success=False, error="Missing 'name' for job")
        if not sched:
            return ToolResult(success=False, error="Missing 'schedule' expression")
        if not task:
            return ToolResult(success=False, error="Missing 'task' description")

        self._store.add(name, sched, task)
        return ToolResult(
            success=True,
            output=f"Job '{name}' scheduled: {sched} -> {task}",
            data={"name": name, "schedule": sched, "task": task},
        )

    def _remove(self, kwargs) -> ToolResult:
        name = kwargs.get("name")
        if not name:
            return ToolResult(success=False, error="Missing 'name'")
        if self._store.remove(name):
            return ToolResult(success=True, output=f"Job '{name}' removed.")
        return ToolResult(success=False, error=f"Job not found: {name}")

    def _toggle(self, kwargs, enabled: bool) -> ToolResult:
        name = kwargs.get("name")
        if not name:
            return ToolResult(success=False, error="Missing 'name'")
        state = "enabled" if enabled else "disabled"
        if self._store.toggle(name, enabled):
            return ToolResult(success=True, output=f"Job '{name}' {state}.")
        return ToolResult(success=False, error=f"Job not found: {name}")

    def _run(self, kwargs) -> ToolResult:
        name = kwargs.get("name")
        if not name:
            return ToolResult(success=False, error="Missing 'name'")
        action = self._store.run_now(name)
        if action:
            return ToolResult(
                success=True,
                output=f"Job '{name}' triggered: {action}",
                data={"name": name, "action": action},
            )
        return ToolResult(success=False, error=f"Job not found: {name}")
