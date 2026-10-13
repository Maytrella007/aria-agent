#!/usr/bin/env python3
"""
ARIA - Complete Setup Script
============================

This script handles the complete installation and configuration of ARIA,
including all Python dependencies.

Usage:
    python scripts/setup_aria.py           # Interactive full setup
    python scripts/setup_aria.py --check   # Check what's installed
    python scripts/setup_aria.py --python  # Python deps only
    python scripts/setup_aria.py --all     # Install everything non-interactively

Requirements:
    - Python 3.10+
    - Internet connection for downloads
"""

import os
import sys
import subprocess
import platform
import argparse
from pathlib import Path
from typing import Tuple, Optional, List, Callable
from dataclasses import dataclass
from enum import Enum
import json


class Colors:
    """ANSI color codes for terminal output"""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

    @classmethod
    def disable(cls):
        """Disable colors for non-TTY output"""
        cls.HEADER = cls.BLUE = cls.CYAN = cls.GREEN = ''
        cls.YELLOW = cls.RED = cls.ENDC = cls.BOLD = ''


# Disable colors if not a TTY
if not sys.stdout.isatty():
    Colors.disable()


class InstallStatus(Enum):
    """Installation status for each component"""
    NOT_INSTALLED = "not_installed"
    INSTALLED = "installed"
    NEEDS_UPDATE = "needs_update"
    CONFIGURED = "configured"
    ERROR = "error"


@dataclass
class ComponentStatus:
    """Status of a single component"""
    name: str
    status: InstallStatus
    version: str = ""
    path: str = ""
    message: str = ""

    def __str__(self) -> str:
        status_colors = {
            InstallStatus.NOT_INSTALLED: Colors.RED,
            InstallStatus.INSTALLED: Colors.GREEN,
            InstallStatus.NEEDS_UPDATE: Colors.YELLOW,
            InstallStatus.CONFIGURED: Colors.GREEN,
            InstallStatus.ERROR: Colors.RED,
        }
        color = status_colors.get(self.status, Colors.ENDC)
        version_str = f" ({self.version})" if self.version else ""
        return f"{color}{self.name}: {self.status.value}{version_str}{Colors.ENDC}"


class ARIASetup:
    """
    Complete setup handler for ARIA.

    Handles:
    - Python version validation
    - Python dependency installation
    - Configuration file setup
    """

    # Minimum versions
    MIN_PYTHON = (3, 10)

    def __init__(self, project_root: str = None):
        self.project_root = Path(project_root or self._find_project_root())
        self.system = platform.system().lower()
        self.is_wsl = "microsoft" in platform.uname().release.lower()

    def _find_project_root(self) -> Path:
        """Find ARIA project root by looking for config.yaml"""
        current = Path(__file__).resolve().parent
        while current != current.parent:
            if (current / "config.yaml").exists():
                return current
            current = current.parent
        return Path.cwd()

    # =========================================================================
    # OUTPUT HELPERS
    # =========================================================================

    def print_header(self, text: str):
        """Print a section header"""
        print(f"\n{Colors.BOLD}{Colors.HEADER}{'='*60}{Colors.ENDC}")
        print(f"{Colors.BOLD}{Colors.HEADER}  {text}{Colors.ENDC}")
        print(f"{Colors.BOLD}{Colors.HEADER}{'='*60}{Colors.ENDC}\n")

    def print_step(self, step: int, total: int, text: str):
        """Print a step indicator"""
        print(f"{Colors.CYAN}[{step}/{total}]{Colors.ENDC} {text}")

    def print_success(self, text: str):
        """Print success message"""
        print(f"{Colors.GREEN}[OK]{Colors.ENDC} {text}")

    def print_warning(self, text: str):
        """Print warning message"""
        print(f"{Colors.YELLOW}[WARN]{Colors.ENDC} {text}")

    def print_error(self, text: str):
        """Print error message"""
        print(f"{Colors.RED}[ERROR]{Colors.ENDC} {text}")

    def print_info(self, text: str):
        """Print info message"""
        print(f"{Colors.BLUE}[INFO]{Colors.ENDC} {text}")

    def ask_yes_no(self, question: str, default: bool = True) -> bool:
        """Ask a yes/no question"""
        default_str = "[Y/n]" if default else "[y/N]"
        while True:
            response = input(f"{question} {default_str}: ").strip().lower()
            if not response:
                return default
            if response in ('y', 'yes'):
                return True
            if response in ('n', 'no'):
                return False
            print("Please answer 'y' or 'n'")

    def ask_choice(self, question: str, options: List[str]) -> int:
        """Ask user to choose from options, returns 0-based index"""
        print(f"\n{question}\n")
        for i, option in enumerate(options, 1):
            print(f"  {i}. {option}")

        while True:
            try:
                choice = input(f"\nChoose [1-{len(options)}]: ").strip()
                idx = int(choice) - 1
                if 0 <= idx < len(options):
                    return idx
            except ValueError:
                pass
            print(f"Please enter a number between 1 and {len(options)}")

    # =========================================================================
    # COMPONENT CHECKS
    # =========================================================================

    def check_python(self) -> ComponentStatus:
        """Check Python version"""
        version = sys.version_info
        version_str = f"{version.major}.{version.minor}.{version.micro}"

        if version >= self.MIN_PYTHON:
            return ComponentStatus(
                name="Python",
                status=InstallStatus.INSTALLED,
                version=version_str,
                path=sys.executable
            )
        return ComponentStatus(
            name="Python",
            status=InstallStatus.NEEDS_UPDATE,
            version=version_str,
            message=f"Requires Python {self.MIN_PYTHON[0]}.{self.MIN_PYTHON[1]}+"
        )

    def check_python_deps(self) -> ComponentStatus:
        """Check if Python dependencies are installed"""
        required = ["yaml", "anthropic", "chromadb", "sentence_transformers"]
        missing = []

        for module in required:
            try:
                __import__(module)
            except ImportError:
                missing.append(module)

        if not missing:
            return ComponentStatus(
                name="Python Deps",
                status=InstallStatus.INSTALLED,
                message="All core dependencies installed"
            )
        return ComponentStatus(
            name="Python Deps",
            status=InstallStatus.NOT_INSTALLED,
            message=f"Missing: {', '.join(missing)}"
        )

    def check_node(self) -> ComponentStatus:
        """Check if Node.js and npx are available (needed for MCP servers)"""
        try:
            result = subprocess.run(
                ["node", "--version"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                version = result.stdout.strip()
                # Also check npx
                npx_result = subprocess.run(
                    ["npx", "--version"],
                    capture_output=True, text=True, timeout=10
                )
                if npx_result.returncode == 0:
                    return ComponentStatus(
                        name="Node.js (MCP)",
                        status=InstallStatus.INSTALLED,
                        version=version,
                        message=f"npx {npx_result.stdout.strip()}"
                    )
                return ComponentStatus(
                    name="Node.js (MCP)",
                    status=InstallStatus.NEEDS_UPDATE,
                    version=version,
                    message="Node.js found but npx missing — reinstall Node.js"
                )
        except FileNotFoundError:
            pass
        except Exception:
            pass

        return ComponentStatus(
            name="Node.js (MCP)",
            status=InstallStatus.NOT_INSTALLED,
            message="Optional — needed for MCP servers (npx @modelcontextprotocol/server-*)"
        )

    def run_diagnostic(self) -> dict:
        """Run complete diagnostic and return status of all components"""
        return {
            "python": self.check_python(),
            "python_deps": self.check_python_deps(),
            "node": self.check_node(),
        }

    # =========================================================================
    # INSTALLATION METHODS
    # =========================================================================

    def install_node(self) -> bool:
        """Install Node.js for MCP server support"""
        self.print_info("Installing Node.js (needed for MCP servers)...")

        try:
            if self.system == "darwin":
                # macOS: try brew
                result = subprocess.run(
                    ["brew", "install", "node"],
                    capture_output=False, timeout=300
                )
                if result.returncode == 0:
                    self.print_success("Node.js installed via Homebrew")
                    return True
                self.print_warning("Homebrew install failed — install manually: https://nodejs.org")
                return False

            elif self.system == "linux" or self.is_wsl:
                # Linux/WSL: try apt, then dnf, then fallback to NodeSource
                for pkg_manager, install_cmd in [
                    ("apt-get", ["sudo", "apt-get", "install", "-y", "nodejs", "npm"]),
                    ("dnf", ["sudo", "dnf", "install", "-y", "nodejs", "npm"]),
                    ("pacman", ["sudo", "pacman", "-S", "--noconfirm", "nodejs", "npm"]),
                ]:
                    # Check if package manager exists
                    check = subprocess.run(
                        ["which", pkg_manager],
                        capture_output=True, timeout=5
                    )
                    if check.returncode == 0:
                        self.print_info(f"Using {pkg_manager}...")
                        if pkg_manager == "apt-get":
                            subprocess.run(
                                ["sudo", "apt-get", "update"],
                                capture_output=True, timeout=120
                            )
                        result = subprocess.run(
                            install_cmd,
                            capture_output=False, timeout=300
                        )
                        if result.returncode == 0:
                            self.print_success(f"Node.js installed via {pkg_manager}")
                            return True

                self.print_warning("Could not auto-install Node.js — install manually: https://nodejs.org")
                return False

            else:
                # Windows or unknown
                self.print_warning("Auto-install not supported on this OS — install from: https://nodejs.org")
                return False

        except Exception as e:
            self.print_warning(f"Node.js install failed: {e}")
            self.print_info("Install manually from: https://nodejs.org")
            return False

    def install_python_deps(self) -> bool:
        """Install Python dependencies from requirements.txt"""
        self.print_step(1, 1, "Installing Python dependencies...")

        req_file = self.project_root / "requirements.txt"
        if not req_file.exists():
            self.print_error(f"requirements.txt not found at {req_file}")
            return False

        try:
            # Use pip to install
            cmd = [sys.executable, "-m", "pip", "install", "-r", str(req_file)]

            # Add --break-system-packages for Debian/Ubuntu with externally managed Python
            if self.system == "linux":
                cmd.append("--break-system-packages")

            result = subprocess.run(
                cmd,
                capture_output=False,
                timeout=600
            )

            if result.returncode == 0:
                self.print_success("Python dependencies installed")
                return True
            else:
                self.print_error("Failed to install some dependencies")
                return False

        except Exception as e:
            self.print_error(f"Error installing dependencies: {e}")
            return False

    # =========================================================================
    # MAIN SETUP FLOWS
    # =========================================================================

    def show_status(self):
        """Show current installation status"""
        self.print_header("ARIA Installation Status")

        diagnostic = self.run_diagnostic()

        for name, status in diagnostic.items():
            print(f"  {status}")

        # Summary
        all_good = all(
            s.status in (InstallStatus.INSTALLED, InstallStatus.CONFIGURED)
            for s in diagnostic.values()
        )

        print()
        if all_good:
            self.print_success("All components installed and configured!")
            print("\nYou can now run ARIA:")
            print("  python aria.py")
        else:
            self.print_warning("Some components need attention.")
            print("\nRun setup to install missing components:")
            print("  python scripts/setup_aria.py")

    def run_full_setup(self, interactive: bool = True):
        """Run the complete setup process"""
        self.print_header("ARIA Complete Setup")

        print("This wizard will install and configure all ARIA components:\n")
        print("  1. Python dependencies (chromadb, sentence-transformers, etc.)")
        print("  2. Node.js (for MCP server support)")
        print()

        if interactive and not self.ask_yes_no("Continue with setup?"):
            print("Setup cancelled.")
            return

        # Step 1: Check Python
        self.print_header("Step 1: Python Environment")
        python_status = self.check_python()
        print(f"  {python_status}")

        if python_status.status == InstallStatus.NEEDS_UPDATE:
            self.print_error(f"Python {self.MIN_PYTHON[0]}.{self.MIN_PYTHON[1]}+ required")
            print("Please upgrade Python and run setup again.")
            return

        # Step 2: Python dependencies
        self.print_header("Step 2: Python Dependencies")
        deps_status = self.check_python_deps()
        print(f"  {deps_status}")

        if deps_status.status != InstallStatus.INSTALLED:
            if not interactive or self.ask_yes_no("Install Python dependencies?"):
                self.install_python_deps()

        # Step 3: Node.js (for MCP servers)
        self.print_header("Step 3: Node.js (MCP Support)")
        node_status = self.check_node()
        print(f"  {node_status}")

        if node_status.status == InstallStatus.NOT_INSTALLED:
            if not interactive or self.ask_yes_no("Install Node.js for MCP server support?"):
                self.install_node()

        # Final status
        self.print_header("Setup Complete")
        self.show_status()

    def run_python_only(self):
        """Install only Python dependencies"""
        self.print_header("Python Dependencies Installation")
        self.install_python_deps()
        print()
        deps_status = self.check_python_deps()
        print(f"  {deps_status}")

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="ARIA Setup - Install and configure all dependencies",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/setup_aria.py           # Interactive full setup
  python scripts/setup_aria.py --check   # Show installation status
  python scripts/setup_aria.py --python  # Install Python deps only
  python scripts/setup_aria.py --all     # Non-interactive full install
"""
    )

    parser.add_argument(
        "--check", "-c",
        action="store_true",
        help="Check installation status without installing"
    )
    parser.add_argument(
        "--python", "-p",
        action="store_true",
        help="Install Python dependencies only"
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Install everything non-interactively"
    )

    args = parser.parse_args()
    setup = ARIASetup()

    try:
        if args.check:
            setup.show_status()
        elif args.python:
            setup.run_python_only()
        elif args.all:
            setup.run_full_setup(interactive=False)
        else:
            setup.run_full_setup(interactive=True)
    except KeyboardInterrupt:
        print("\n\nSetup cancelled by user.")
        sys.exit(1)


if __name__ == "__main__":
    main()
