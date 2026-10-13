"""
Git Operations Skill - Full git workflow management.

Exposes all git operations (status, commit, branch, merge, push, pull, etc.)
through natural language. Uses git tool for execution and LLM for formatting.
"""

import re

from .base import SkillBase, SkillResult, SkillContext
from core.tools.tool_names import Tools


class GitOpsSkill(SkillBase):
    name = "git_ops"
    description = (
        "Full git operations: status, log, diff, commit, branch, checkout, "
        "push, pull, merge, rebase, stash, tag, blame, clone, and overview"
    )
    requires_tools = [Tools.GIT]

    def _execute(self, query: str, ctx: SkillContext) -> SkillResult:
        if not ctx.tools:
            return SkillResult(success=False, error="No tools available")

        op, args = self._parse_query(query)
        handler = getattr(self, f"_op_{op}", None)
        if handler:
            return handler(args, ctx)
        return self._op_overview(args, ctx)

    # -------------------------------------------------------------------------
    # Query parsing — detect operation + extract arguments
    # -------------------------------------------------------------------------

    def _parse_query(self, query: str) -> tuple:
        """Parse query into (operation, remaining_args)."""
        q = query.lower().strip()

        # Ordered keyword map — check multi-word phrases first, then single words.
        # Order matters: more specific operations come before generic ones.
        OP_KEYWORDS = [
            # Multi-word phrases first (prevents partial matches)
            ("log", ["commit history", "recent commits", "últimos commits"]),
            ("commit", ["save changes", "guardar cambios", "commit"]),
            ("stash", ["guardar temporal", "stash"]),
            ("checkout", ["switch to", "cambiar a", "checkout", "switch"]),
            ("push", ["push changes", "push", "subir"]),
            ("pull", ["pull changes", "pull", "bajar", "actualizar"]),
            ("merge", ["merge branch", "merge", "fusionar"]),
            ("rebase", ["rebase"]),
            ("clone", ["clone", "clonar"]),
            ("init", ["initialize", "inicializar", "init"]),
            ("blame", ["who changed", "quién cambió", "blame", "annotate"]),
            ("overview", ["overview", "git summary", "summary", "resumen"]),
            ("log", ["history", "historial", "commits", "log"]),
            ("diff", ["what changed", "qué cambió", "diff", "changes", "cambios"]),
            ("status", ["git status", "status", "estado"]),
            ("tag", ["tags", "etiquetas", "tag", "etiqueta"]),
            ("remote", ["remotes", "remotos", "remote"]),
            ("branch", ["branches", "ramas", "branch", "rama"]),
            ("add", ["add files", "stage", "add", "agregar"]),
        ]

        for op, keywords in OP_KEYWORDS:
            for kw in keywords:
                if kw in q:
                    # Remove the keyword to get remaining args
                    remaining = q.replace(kw, "").strip()
                    # Also strip common prefixes
                    remaining = re.sub(r'^(git\s+|por favor\s+|please\s+)', '', remaining).strip()
                    return op, remaining or query

        return "overview", query

    # -------------------------------------------------------------------------
    # Operations
    # -------------------------------------------------------------------------

    def _op_status(self, args: str, ctx: SkillContext) -> SkillResult:
        """Working tree status with formatted output."""
        result = ctx.tools.execute(Tools.GIT, action="status")
        if not result.success:
            return SkillResult(success=False, error=f"Git status failed: {result.error}")

        files = result.data.get("files", {})
        if ctx.llm and result.output.strip():
            return self._format_with_llm("status", result.output, ctx)

        return SkillResult(
            success=True,
            output=result.output or "Working tree clean.",
            data={"operation": "status", "files": files},
        )

    def _op_log(self, args: str, ctx: SkillContext) -> SkillResult:
        """Recent commit log."""
        n = 10
        n_match = re.search(r'(\d+)', args)
        if n_match:
            n = min(int(n_match.group(1)), 50)

        result = ctx.tools.execute(Tools.GIT, action="log", args=f"-{n}")
        if not result.success:
            return SkillResult(success=False, error=f"Git log failed: {result.error}")

        if ctx.llm:
            return self._format_with_llm("log", result.output, ctx)

        return SkillResult(
            success=True,
            output=result.output,
            data={"operation": "log", "count": n},
        )

    def _op_diff(self, args: str, ctx: SkillContext) -> SkillResult:
        """Show uncommitted changes."""
        kwargs = {"action": "diff"}
        # Check for specific file
        file_match = re.search(r'(\S+\.\w+)', args)
        if file_match:
            kwargs["args"] = file_match.group(1)

        # Check for staged flag
        if any(w in args.lower() for w in ["staged", "cached", "preparados"]):
            kwargs["args"] = "--cached"

        result = ctx.tools.execute(Tools.GIT, **kwargs)
        if not result.success:
            return SkillResult(success=False, error=f"Git diff failed: {result.error}")

        if not result.output or result.output.strip() == "" or result.output == "(no output)":
            return SkillResult(
                success=True,
                output="No uncommitted changes.",
                data={"operation": "diff", "clean": True},
            )

        if ctx.llm:
            return self._format_with_llm("diff", result.output, ctx)

        return SkillResult(
            success=True,
            output=result.output[:3000],
            data={"operation": "diff"},
        )

    def _op_commit(self, args: str, ctx: SkillContext) -> SkillResult:
        """Create a commit with a message."""
        message = self._extract_commit_message(args)
        if not message:
            # Try to generate a message with LLM
            if ctx.llm:
                diff = ctx.tools.execute(Tools.GIT, action="diff")
                status = ctx.tools.execute(Tools.GIT, action="status")
                if diff.success and diff.output.strip():
                    message = self._generate_commit_message(diff.output, status.output, ctx)

            if not message:
                return SkillResult(
                    success=False,
                    error="No commit message provided. Use: commit 'your message' or describe the changes.",
                )

        # Stage all if nothing is staged
        status = ctx.tools.execute(Tools.GIT, action="status")
        if status.success:
            files = status.data.get("files", {})
            if not files.get("staged") and (files.get("modified") or files.get("untracked")):
                ctx.tools.execute(Tools.GIT, action="add", args=".")

        result = ctx.tools.execute(Tools.GIT, action="commit", args=message)
        if not result.success:
            return SkillResult(success=False, error=f"Commit failed: {result.error}")

        return SkillResult(
            success=True,
            output=f"Committed: {message}\n{result.output}",
            data={"operation": "commit", "message": message},
        )

    def _op_branch(self, args: str, ctx: SkillContext) -> SkillResult:
        """List, create, or delete branches."""
        git_args = ""
        op_detail = "list"

        if any(w in args.lower() for w in ["all", "todas", "-a"]):
            git_args = "-a"
        elif any(w in args.lower() for w in ["delete", "borrar", "eliminar", "-d"]):
            branch_name = re.search(r'(?:delete|borrar|eliminar|-d)\s+(\S+)', args)
            if branch_name:
                git_args = f"-d {branch_name.group(1)}"
                op_detail = "delete"
        elif args.strip() and not args.startswith("-"):
            # Create new branch
            branch_name = args.strip().split()[0]
            git_args = branch_name
            op_detail = "create"

        result = ctx.tools.execute(Tools.GIT, action="branch", args=git_args)
        if not result.success:
            return SkillResult(success=False, error=f"Branch operation failed: {result.error}")

        return SkillResult(
            success=True,
            output=result.output,
            data={"operation": "branch", "detail": op_detail},
        )

    def _op_checkout(self, args: str, ctx: SkillContext) -> SkillResult:
        """Switch branches or restore files."""
        target = args.strip().split()[0] if args.strip() else ""
        if not target:
            return SkillResult(success=False, error="Specify a branch or file to checkout.")

        # Check for -b (create + switch)
        if any(w in args.lower() for w in ["new", "crear", "create", "-b"]):
            result = ctx.tools.execute(Tools.GIT, action="checkout", args=f"-b {target}")
        else:
            result = ctx.tools.execute(Tools.GIT, action="checkout", args=target)

        if not result.success:
            return SkillResult(success=False, error=f"Checkout failed: {result.error}")

        return SkillResult(
            success=True,
            output=f"Switched to: {target}\n{result.output}",
            data={"operation": "checkout", "target": target},
        )

    def _op_push(self, args: str, ctx: SkillContext) -> SkillResult:
        """Push commits to remote."""
        git_args = args.strip() if args.strip() else ""

        # Detect --set-upstream pattern
        if any(w in args.lower() for w in ["upstream", "-u"]):
            git_args = f"-u origin {args.split()[-1]}" if args.split() else "-u origin HEAD"

        result = ctx.tools.execute(Tools.GIT, action="push", args=git_args)
        if not result.success:
            return SkillResult(success=False, error=f"Push failed: {result.error}")

        return SkillResult(
            success=True,
            output=f"Pushed successfully.\n{result.output}",
            data={"operation": "push"},
        )

    def _op_pull(self, args: str, ctx: SkillContext) -> SkillResult:
        """Pull changes from remote."""
        result = ctx.tools.execute(Tools.GIT, action="pull", args=args.strip())
        if not result.success:
            return SkillResult(success=False, error=f"Pull failed: {result.error}")

        return SkillResult(
            success=True,
            output=f"Pulled successfully.\n{result.output}",
            data={"operation": "pull"},
        )

    def _op_merge(self, args: str, ctx: SkillContext) -> SkillResult:
        """Merge a branch."""
        branch = args.strip().split()[0] if args.strip() else ""
        if not branch:
            return SkillResult(success=False, error="Specify a branch to merge.")

        result = ctx.tools.execute(Tools.GIT, action="merge", args=branch)
        if not result.success:
            # Check for merge conflict
            if "conflict" in (result.error or "").lower():
                return SkillResult(
                    success=False,
                    error=f"Merge conflict detected:\n{result.output}",
                    data={"operation": "merge", "conflict": True},
                )
            return SkillResult(success=False, error=f"Merge failed: {result.error}")

        return SkillResult(
            success=True,
            output=f"Merged '{branch}' successfully.\n{result.output}",
            data={"operation": "merge", "branch": branch},
        )

    def _op_rebase(self, args: str, ctx: SkillContext) -> SkillResult:
        """Rebase onto a branch."""
        target = args.strip().split()[0] if args.strip() else ""
        if not target:
            return SkillResult(success=False, error="Specify a branch to rebase onto.")

        result = ctx.tools.execute(Tools.GIT, action="rebase", args=target)
        if not result.success:
            return SkillResult(success=False, error=f"Rebase failed: {result.error}")

        return SkillResult(
            success=True,
            output=f"Rebased onto '{target}' successfully.\n{result.output}",
            data={"operation": "rebase", "target": target},
        )

    def _op_stash(self, args: str, ctx: SkillContext) -> SkillResult:
        """Stash or unstash changes."""
        q = args.lower()
        if any(w in q for w in ["pop", "apply", "recuperar", "restore"]):
            git_args = "pop"
        elif any(w in q for w in ["list", "listar", "show"]):
            git_args = "list"
        elif any(w in q for w in ["drop", "borrar", "delete"]):
            git_args = "drop"
        else:
            git_args = ""  # Default: stash save

        result = ctx.tools.execute(Tools.GIT, action="stash", args=git_args)
        if not result.success:
            return SkillResult(success=False, error=f"Stash failed: {result.error}")

        return SkillResult(
            success=True,
            output=result.output or "Changes stashed.",
            data={"operation": "stash", "subcommand": git_args or "save"},
        )

    def _op_tag(self, args: str, ctx: SkillContext) -> SkillResult:
        """Create or list tags."""
        if not args.strip():
            # List tags
            result = ctx.tools.execute(Tools.GIT, action="tag")
        else:
            tag_name = args.strip().split()[0]
            result = ctx.tools.execute(Tools.GIT, action="tag", args=tag_name)

        if not result.success:
            return SkillResult(success=False, error=f"Tag operation failed: {result.error}")

        return SkillResult(
            success=True,
            output=result.output or f"Tag created: {args.strip()}",
            data={"operation": "tag"},
        )

    def _op_blame(self, args: str, ctx: SkillContext) -> SkillResult:
        """Show file annotation (who changed what)."""
        file_match = re.search(r'(\S+\.\w+)', args)
        if not file_match:
            return SkillResult(success=False, error="Specify a file to blame.")

        filepath = file_match.group(1)
        result = ctx.tools.execute(Tools.GIT, action="blame", args=filepath)
        if not result.success:
            return SkillResult(success=False, error=f"Blame failed: {result.error}")

        if ctx.llm:
            return self._format_with_llm("blame", result.output, ctx)

        return SkillResult(
            success=True,
            output=result.output[:3000],
            data={"operation": "blame", "file": filepath},
        )

    def _op_add(self, args: str, ctx: SkillContext) -> SkillResult:
        """Stage files for commit."""
        files = args.strip() if args.strip() else "."
        result = ctx.tools.execute(Tools.GIT, action="add", args=files)
        if not result.success:
            return SkillResult(success=False, error=f"Add failed: {result.error}")

        return SkillResult(
            success=True,
            output=f"Staged: {files}\n{result.output}",
            data={"operation": "add", "files": files},
        )

    def _op_clone(self, args: str, ctx: SkillContext) -> SkillResult:
        """Clone a repository."""
        url_match = re.search(r'(https?://\S+|git@\S+)', args)
        if not url_match:
            return SkillResult(success=False, error="Provide a repository URL to clone.")

        url = url_match.group(1)
        result = ctx.tools.execute(Tools.GIT, action="clone", args=url)
        if not result.success:
            return SkillResult(success=False, error=f"Clone failed: {result.error}")

        return SkillResult(
            success=True,
            output=f"Cloned: {url}\n{result.output}",
            data={"operation": "clone", "url": url},
        )

    def _op_init(self, args: str, ctx: SkillContext) -> SkillResult:
        """Initialize a new git repository."""
        result = ctx.tools.execute(Tools.GIT, action="init")
        if not result.success:
            return SkillResult(success=False, error=f"Init failed: {result.error}")

        return SkillResult(
            success=True,
            output=f"Repository initialized.\n{result.output}",
            data={"operation": "init"},
        )

    def _op_remote(self, args: str, ctx: SkillContext) -> SkillResult:
        """Show or manage remotes."""
        git_args = args.strip() if args.strip() else "-v"
        result = ctx.tools.execute(Tools.GIT, action="remote", args=git_args)
        if not result.success:
            return SkillResult(success=False, error=f"Remote operation failed: {result.error}")

        return SkillResult(
            success=True,
            output=result.output or "No remotes configured.",
            data={"operation": "remote"},
        )

    def _op_overview(self, args: str, ctx: SkillContext) -> SkillResult:
        """Comprehensive git overview (status + log + branches)."""
        parts = []

        status = ctx.tools.execute(Tools.GIT, action="status")
        if status.success:
            parts.append(("Status", status.output))

        log = ctx.tools.execute(Tools.GIT, action="log", args="-5")
        if log.success:
            parts.append(("Recent Commits", log.output))

        branch = ctx.tools.execute(Tools.GIT, action="branch")
        if branch.success:
            parts.append(("Branches", branch.output))

        if not parts:
            return SkillResult(success=False, error="Could not retrieve git information")

        if ctx.llm:
            raw = "\n\n".join(f"=== {title} ===\n{content}" for title, content in parts)
            return self._format_with_llm("overview", raw, ctx)

        output = "\n\n".join(f"## {title}\n{content}" for title, content in parts)
        return SkillResult(
            success=True,
            output=output,
            data={"operation": "overview"},
        )

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _extract_commit_message(self, args: str) -> str:
        """Extract commit message from various formats."""
        # Quoted message: commit "message" or commit 'message'
        quoted = re.search(r'''['"](.*?)['"]''', args)
        if quoted:
            return quoted.group(1)

        # After "message:" or "msg:" or ":"
        msg_prefix = re.search(r'(?:message|msg|mensaje)\s*:\s*(.+)', args, re.IGNORECASE)
        if msg_prefix:
            return msg_prefix.group(1).strip()

        # If it looks like a direct message (not a command word)
        clean = re.sub(r'^(commit|guardar|save)\s+', '', args, flags=re.IGNORECASE).strip()
        if clean and len(clean) > 3:
            return clean

        return ""

    def _generate_commit_message(self, diff: str, status: str, ctx: SkillContext) -> str:
        """Use LLM to generate a commit message from diff."""
        prompt = f"""Generate a concise git commit message (max 72 chars) for these changes.
Use conventional commit format (feat:, fix:, refactor:, docs:, etc.).

Status:
{status[:1000]}

Diff:
{diff[:2000]}

Respond with ONLY the commit message, nothing else."""

        try:
            response = ctx.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
            )
            if response and response.content:
                msg = response.content.strip().strip('"').strip("'")
                return msg[:72]
        except Exception:
            pass
        return ""

    def _format_with_llm(self, op_type: str, raw_data: str, ctx: SkillContext) -> SkillResult:
        """Use LLM to create a clean, readable summary."""
        prompt = f"""Summarize this git {op_type} output into a clean, readable format:

{raw_data[:4000]}

Requirements:
- Use bullet points for commits
- Highlight important changes
- Group related changes if possible
- Keep it concise and scannable
- If it's a diff, explain what changed in plain language"""

        try:
            response = ctx.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
            )
            if response and response.content:
                return SkillResult(
                    success=True,
                    output=response.content,
                    data={"operation": op_type, "formatted": True},
                )
        except Exception:
            pass

        return SkillResult(
            success=True,
            output=raw_data[:2000],
            data={"operation": op_type, "formatted": False},
        )
