"""
ARIA - Git Tool (Hardened)
===========================

Git operations with a clean, secure interface.
- No shell=True (prevents injection)
- Structured output parsing for log, status, diff
- Added: merge, rebase, tag, blame
"""

import logging
import os
import re
import subprocess
from typing import Any, Dict, List, Optional

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.git")

DEFAULT_TIMEOUT = 30

# Characters not allowed in git arguments (prevent shell tricks)
DANGEROUS_CHARS = set(";|&$`\n\r")


def _sanitize(arg: str) -> str:
    """Reject arguments containing shell metacharacters."""
    if any(c in DANGEROUS_CHARS for c in arg):
        raise ValueError(f"Argument contains forbidden characters: {arg!r}")
    return arg


def _parse_log(text: str) -> List[Dict[str, str]]:
    """Parse git log --format output into structured commits."""
    commits = []
    for line in text.strip().splitlines():
        parts = line.split("|", 3)
        if len(parts) == 4:
            commits.append({
                "hash": parts[0].strip(),
                "author": parts[1].strip(),
                "date": parts[2].strip(),
                "message": parts[3].strip(),
            })
    return commits


def _parse_status(text: str) -> Dict[str, List[str]]:
    """Parse git status --porcelain into structured data."""
    staged, modified, untracked = [], [], []
    for line in text.strip().splitlines():
        if len(line) < 3:
            continue
        x, y, path = line[0], line[1], line[3:]
        if x in "MADRC":
            staged.append(path)
        if y in "MD":
            modified.append(path)
        if x == "?" and y == "?":
            untracked.append(path)
    return {"staged": staged, "modified": modified, "untracked": untracked}


class GitTool(ToolBase):
    """Perform git operations on repositories."""

    name = "git"
    description = (
        "Perform git operations: status, log, diff, commit, branch, checkout, "
        "pull, push, stash, add, init, clone, remote, merge, rebase, tag, blame. "
        "Provide a repo_path or it defaults to the current directory."
    )
    parameters = [
        ToolParam(
            name="action",
            type="string",
            description="Git action to perform",
            required=True,
            enum=[
                "status", "log", "diff", "commit", "branch",
                "checkout", "pull", "push", "stash", "add",
                "init", "clone", "remote", "merge", "rebase",
                "tag", "blame",
            ],
        ),
        ToolParam(
            name="args",
            type="string",
            description=(
                "Additional arguments. Examples: "
                "commit: 'message text', "
                "log: '-10', "
                "checkout: 'branch-name', "
                "add: '. or file.py', "
                "clone: 'https://github.com/user/repo.git', "
                "branch: '-a' or 'new-branch', "
                "merge: 'feature-branch', "
                "tag: 'v1.0.0', "
                "blame: 'file.py'"
            ),
            required=False,
            default="",
        ),
        ToolParam(
            name="repo_path",
            type="string",
            description="Path to the git repository (default: current directory)",
            required=False,
        ),
    ]

    def _execute(self, **kwargs) -> ToolResult:
        action = kwargs["action"]
        args = kwargs.get("args", "").strip()
        repo_path = kwargs.get("repo_path")

        if repo_path:
            repo_path = os.path.expanduser(repo_path)
            if not os.path.isdir(repo_path):
                return ToolResult(success=False, error=f"Directory not found: {repo_path}")

        try:
            cmd_list = self._build_command(action, args)
        except ValueError as e:
            return ToolResult(success=False, error=str(e))

        if cmd_list is None:
            return ToolResult(success=False, error=f"Invalid arguments for action: {action}")

        result = self._run_git(cmd_list, cwd=repo_path)

        # Post-process: parse structured data for certain actions
        if result.success and action == "log":
            commits = _parse_log(result.data.get("stdout", ""))
            if commits:
                result.data["commits"] = commits
        elif result.success and action == "status":
            parsed = _parse_status(result.data.get("stdout_raw", ""))
            result.data["files"] = parsed

        return result

    def _build_command(self, action: str, args: str) -> Optional[List[str]]:
        """Build git command as a list (no shell). Returns None on invalid input."""
        extra = [_sanitize(a) for a in args.split() if a] if args else []

        if action == "status":
            return ["git", "status", "--porcelain"] + extra

        elif action == "log":
            n = "20"
            if extra and extra[0].lstrip("-").isdigit():
                n = extra.pop(0).lstrip("-")
            return ["git", "log", f"--format=%h|%an|%ad|%s", "--date=short", f"-{n}"] + extra

        elif action == "diff":
            return ["git", "diff"] + extra

        elif action == "commit":
            if not args:
                return None
            _sanitize(args)
            return ["git", "commit", "-m", args]

        elif action == "branch":
            return ["git", "branch"] + extra

        elif action == "checkout":
            if not extra:
                return None
            return ["git", "checkout"] + extra

        elif action == "pull":
            return ["git", "pull"] + extra

        elif action == "push":
            return ["git", "push"] + extra

        elif action == "stash":
            return ["git", "stash"] + extra

        elif action == "add":
            if not extra:
                extra = ["."]
            return ["git", "add"] + extra

        elif action == "init":
            return ["git", "init"]

        elif action == "clone":
            if not extra:
                return None
            return ["git", "clone"] + extra

        elif action == "remote":
            if not extra:
                extra = ["-v"]
            return ["git", "remote"] + extra

        elif action == "merge":
            if not extra:
                return None
            return ["git", "merge"] + extra

        elif action == "rebase":
            if not extra:
                return None
            return ["git", "rebase"] + extra

        elif action == "tag":
            return ["git", "tag"] + extra

        elif action == "blame":
            if not extra:
                return None
            return ["git", "blame"] + extra

        return None

    def _run_git(self, cmd: List[str], cwd: Optional[str] = None) -> ToolResult:
        """Execute a git command safely (no shell) and return the result."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=DEFAULT_TIMEOUT,
                cwd=cwd,
            )

            stdout = result.stdout.strip()
            stderr = result.stderr.strip()
            success = result.returncode == 0

            output_parts = []
            if stdout:
                output_parts.append(stdout)
            if stderr:
                if success:
                    output_parts.append(stderr)
                else:
                    output_parts.append(f"Error: {stderr}")

            output = "\n".join(output_parts) if output_parts else "(no output)"

            return ToolResult(
                success=success,
                output=output,
                data={
                    "command": " ".join(cmd),
                    "return_code": result.returncode,
                    "stdout": stdout[:10000],
                    "stdout_raw": result.stdout[:10000],
                    "stderr": stderr[:5000],
                },
                error=stderr if not success else None,
            )

        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error=f"Git command timed out after {DEFAULT_TIMEOUT}s")
        except FileNotFoundError:
            return ToolResult(success=False, error="git not found. Is git installed?")
        except Exception as e:
            return ToolResult(success=False, error=str(e))
