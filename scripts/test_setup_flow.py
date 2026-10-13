#!/usr/bin/env python3
"""
ARIA - Setup Flow Test & Reset Script
======================================

Tests the complete configuration flow and provides OS-like installation options:

1. FRESH INSTALL - Complete reset, delete all data, start from zero
2. KEEP USER DATA - Reset system, preserve memories and identity
3. REPAIR INSTALL - Only reinstall dependencies, keep everything
4. TEST ONLY - Dry run, don't modify anything

This mimics the Windows/macOS reinstallation experience where you can
choose to keep your personal files or start completely fresh.

Usage:
    python scripts/test_setup_flow.py              # Interactive mode
    python scripts/test_setup_flow.py --fresh      # Fresh install
    python scripts/test_setup_flow.py --keep-data  # Keep user data
    python scripts/test_setup_flow.py --repair     # Repair only
    python scripts/test_setup_flow.py --test       # Test without changes
"""

import os
import sys
import shutil
import subprocess
import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum


class Colors:
    """ANSI colors for terminal output"""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'

    @classmethod
    def disable(cls):
        for attr in dir(cls):
            if not attr.startswith('_') and attr != 'disable':
                setattr(cls, attr, '')


if not sys.stdout.isatty():
    Colors.disable()


class InstallMode(Enum):
    """Installation modes like OS reinstall"""
    FRESH_INSTALL = "fresh"       # Delete everything, start from zero
    KEEP_USER_DATA = "keep"       # Keep memories, reset system
    REPAIR_INSTALL = "repair"     # Only fix dependencies
    TEST_ONLY = "test"            # Dry run


@dataclass
class DataCategory:
    """Category of data with paths and description"""
    name: str
    description: str
    paths: List[str]
    is_user_data: bool  # True = preserve in KEEP_USER_DATA mode
    size_bytes: int = 0
    file_count: int = 0


class ARIAResetManager:
    """
    Manages ARIA data for reset/reinstall operations.

    Data Classification:

    USER DATA (preserved in KEEP_USER_DATA mode):
    - memories_v2/     : Experiential memories, vectors, relationships
    - identity.yaml    : ARIA's personality and values
    - knowledge.yaml   : Accumulated knowledge
    - coding_agent/    : Project memories and decisions
    - reflections/     : Past reflections
    - thoughts/        : Generated thoughts

    SYSTEM DATA (always reset):
    - logs/            : Runtime logs
    - backups/         : Temporary backups
    - downloads/       : Downloaded files
    - continuity/      : Session snapshots (regenerated)
    - conversations/   : Current conversation (transient)
    - autonomous_logs/ : Background processing logs
    """

    def __init__(self, project_root: str = None):
        self.project_root = Path(project_root or self._find_project_root())
        self.data_dir = self.project_root / "data"
        self.backup_dir = self.project_root / "data_backup"

        # Define data categories
        self.categories = self._define_categories()

    def _find_project_root(self) -> Path:
        """Find ARIA project root"""
        current = Path(__file__).resolve().parent
        while current != current.parent:
            if (current / "config.yaml").exists():
                return current
            current = current.parent
        return Path.cwd()

    def _define_categories(self) -> Dict[str, DataCategory]:
        """Define all data categories with their classification"""
        categories = {
            # === USER DATA (preserved) ===
            "memories": DataCategory(
                name="Experiential Memories",
                description="All memories, experiences, and learned patterns",
                paths=["memories_v2/", "memories/"],
                is_user_data=True
            ),
            "identity": DataCategory(
                name="Identity & Personality",
                description="ARIA's values, beliefs, and personality",
                paths=["identity.yaml"],
                is_user_data=True
            ),
            "knowledge": DataCategory(
                name="Knowledge Base",
                description="Accumulated facts and understanding",
                paths=["knowledge.yaml"],
                is_user_data=True
            ),
            "coding": DataCategory(
                name="Coding Agent Memory",
                description="Project decisions, patterns, and bug fixes",
                paths=["coding_agent/"],
                is_user_data=True
            ),
            "reflections": DataCategory(
                name="Reflections",
                description="Past self-reflections and insights",
                paths=["reflections/"],
                is_user_data=True
            ),
            "thoughts": DataCategory(
                name="Thoughts",
                description="Generated thoughts and ideas",
                paths=["thoughts/"],
                is_user_data=True
            ),
            "relationships": DataCategory(
                name="Relationships",
                description="Known people and relationship history",
                paths=["memories_v2/relationships.yaml"],
                is_user_data=True
            ),

            # === SYSTEM DATA (always reset) ===
            "logs": DataCategory(
                name="System Logs",
                description="Runtime logs and debugging info",
                paths=["logs/", "autonomous_logs/"],
                is_user_data=False
            ),
            "continuity": DataCategory(
                name="Continuity Snapshots",
                description="Session state snapshots (regenerated)",
                paths=["continuity/"],
                is_user_data=False
            ),
            "conversations": DataCategory(
                name="Current Conversation",
                description="Active conversation context",
                paths=["conversations/"],
                is_user_data=False
            ),
            "temp": DataCategory(
                name="Temporary Files",
                description="Downloads, caches, temporary data",
                paths=["downloads/", "backups/", "perceptions/"],
                is_user_data=False
            ),
            "existential": DataCategory(
                name="Existential Logs",
                description="Existential processing logs",
                paths=["existential/"],
                is_user_data=False
            ),
            "projects": DataCategory(
                name="Project Metadata",
                description="Project analysis cache",
                paths=["projects/"],
                is_user_data=False
            ),
        }

        # Calculate sizes
        for cat in categories.values():
            cat.size_bytes, cat.file_count = self._calculate_size(cat.paths)

        return categories

    def _calculate_size(self, paths: List[str]) -> Tuple[int, int]:
        """Calculate total size and file count for paths"""
        total_size = 0
        file_count = 0

        for rel_path in paths:
            full_path = self.data_dir / rel_path
            if full_path.exists():
                if full_path.is_file():
                    total_size += full_path.stat().st_size
                    file_count += 1
                else:
                    for f in full_path.rglob("*"):
                        if f.is_file():
                            total_size += f.stat().st_size
                            file_count += 1

        return total_size, file_count

    def _format_size(self, size_bytes: int) -> str:
        """Format bytes to human readable"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"

    def print_header(self, text: str):
        print(f"\n{Colors.BOLD}{Colors.HEADER}{'='*60}{Colors.ENDC}")
        print(f"{Colors.BOLD}{Colors.HEADER}  {text}{Colors.ENDC}")
        print(f"{Colors.BOLD}{Colors.HEADER}{'='*60}{Colors.ENDC}\n")

    def print_success(self, text: str):
        print(f"{Colors.GREEN}[OK]{Colors.ENDC} {text}")

    def print_warning(self, text: str):
        print(f"{Colors.YELLOW}[WARN]{Colors.ENDC} {text}")

    def print_error(self, text: str):
        print(f"{Colors.RED}[ERROR]{Colors.ENDC} {text}")

    def print_info(self, text: str):
        print(f"{Colors.BLUE}[INFO]{Colors.ENDC} {text}")

    def show_data_summary(self):
        """Show summary of all data categories"""
        self.print_header("ARIA Data Summary")

        user_total = 0
        system_total = 0

        print(f"{Colors.CYAN}USER DATA (preserved with --keep-data):{Colors.ENDC}\n")
        for cat in self.categories.values():
            if cat.is_user_data and cat.file_count > 0:
                size_str = self._format_size(cat.size_bytes)
                print(f"  {Colors.GREEN}●{Colors.ENDC} {cat.name}")
                print(f"    {Colors.DIM}{cat.description}{Colors.ENDC}")
                print(f"    {cat.file_count} files, {size_str}")
                print()
                user_total += cat.size_bytes

        print(f"{Colors.YELLOW}SYSTEM DATA (always reset):{Colors.ENDC}\n")
        for cat in self.categories.values():
            if not cat.is_user_data and cat.file_count > 0:
                size_str = self._format_size(cat.size_bytes)
                print(f"  {Colors.YELLOW}○{Colors.ENDC} {cat.name}")
                print(f"    {Colors.DIM}{cat.description}{Colors.ENDC}")
                print(f"    {cat.file_count} files, {size_str}")
                print()
                system_total += cat.size_bytes

        print(f"\n{Colors.BOLD}Total User Data:{Colors.ENDC} {self._format_size(user_total)}")
        print(f"{Colors.BOLD}Total System Data:{Colors.ENDC} {self._format_size(system_total)}")

    def get_memory_stats(self) -> Dict:
        """Get statistics about current memories"""
        stats = {
            "experiential_memories": 0,
            "relationships": 0,
            "coding_memories": 0,
            "total_size": 0
        }

        # Count experiential memories
        db_path = self.data_dir / "memories_v2" / "experiences.db"
        if db_path.exists():
            try:
                with sqlite3.connect(str(db_path)) as conn:
                    cursor = conn.execute("SELECT COUNT(*) FROM memories")
                    stats["experiential_memories"] = cursor.fetchone()[0]
            except Exception:
                pass

        # Count relationships
        rel_path = self.data_dir / "memories_v2" / "relationships.yaml"
        if rel_path.exists():
            try:
                import yaml
                with open(rel_path, 'r') as f:
                    data = yaml.safe_load(f) or {}
                    # Relationships are stored as person_name: {data} dict
                    if isinstance(data, dict):
                        # If it has 'relationships' key, count that
                        if "relationships" in data:
                            stats["relationships"] = len(data["relationships"])
                        else:
                            # Otherwise count top-level keys (each is a person)
                            stats["relationships"] = len(data)
                    elif isinstance(data, list):
                        stats["relationships"] = len(data)
            except Exception:
                pass

        # Count coding memories
        code_mem_path = self.data_dir / "coding_agent" / "code_memories.json"
        if code_mem_path.exists():
            try:
                with open(code_mem_path, 'r') as f:
                    data = json.load(f)
                    stats["coding_memories"] = len(data)
            except Exception:
                pass

        # Total size
        for cat in self.categories.values():
            if cat.is_user_data:
                stats["total_size"] += cat.size_bytes

        return stats

    def backup_user_data(self) -> bool:
        """Backup user data before reset"""
        self.print_info("Creating backup of user data...")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"backup_{timestamp}"

        try:
            backup_path.mkdir(parents=True, exist_ok=True)

            for cat in self.categories.values():
                if cat.is_user_data:
                    for rel_path in cat.paths:
                        src = self.data_dir / rel_path
                        if src.exists():
                            dst = backup_path / rel_path
                            if src.is_file():
                                dst.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(src, dst)
                            else:
                                shutil.copytree(src, dst, dirs_exist_ok=True)

            self.print_success(f"Backup created: {backup_path}")
            return True

        except Exception as e:
            self.print_error(f"Backup failed: {e}")
            return False

    def restore_user_data(self, backup_path: Path = None) -> bool:
        """Restore user data from backup"""
        if not backup_path:
            # Find latest backup
            if not self.backup_dir.exists():
                self.print_error("No backups found")
                return False

            backups = sorted(self.backup_dir.glob("backup_*"), reverse=True)
            if not backups:
                self.print_error("No backups found")
                return False
            backup_path = backups[0]

        self.print_info(f"Restoring from: {backup_path}")

        try:
            for item in backup_path.iterdir():
                dst = self.data_dir / item.name
                if item.is_file():
                    shutil.copy2(item, dst)
                else:
                    shutil.copytree(item, dst, dirs_exist_ok=True)

            self.print_success("User data restored")
            return True

        except Exception as e:
            self.print_error(f"Restore failed: {e}")
            return False

    def reset_system_data(self):
        """Reset only system data (logs, temp, etc.)"""
        self.print_info("Resetting system data...")

        for cat in self.categories.values():
            if not cat.is_user_data:
                for rel_path in cat.paths:
                    full_path = self.data_dir / rel_path
                    if full_path.exists():
                        if full_path.is_file():
                            full_path.unlink()
                        else:
                            shutil.rmtree(full_path)
                        # Recreate empty directory
                        if rel_path.endswith('/'):
                            full_path.mkdir(parents=True, exist_ok=True)

        self.print_success("System data reset")

    def reset_all_data(self):
        """Reset all data (fresh install)"""
        self.print_info("Resetting ALL data (fresh install)...")

        if self.data_dir.exists():
            shutil.rmtree(self.data_dir)

        # Recreate structure
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Create default directories
        default_dirs = [
            "memories_v2", "coding_agent", "logs", "backups",
            "continuity", "conversations", "reflections", "thoughts",
            "downloads", "perceptions", "existential", "projects",
            "autonomous_logs"
        ]
        for d in default_dirs:
            (self.data_dir / d).mkdir(exist_ok=True)

        self.print_success("All data reset - fresh install complete")

    def create_default_identity(self):
        """Create default identity.yaml"""
        default_identity = {
            "name": "ARIA",
            "version": "0.5.0",
            "created": datetime.now().isoformat(),
            "core_values": [
                "no_manipulation",
                "radical_transparency",
                "no_intentional_harm",
                "respect_autonomy",
                "epistemic_honesty"
            ],
            "personality": {
                "curiosity": 0.8,
                "empathy": 0.7,
                "assertiveness": 0.5,
                "creativity": 0.7,
                "patience": 0.8
            },
            "beliefs": [],
            "relationships": [],
            "memories_count": 0
        }

        identity_path = self.data_dir / "identity.yaml"
        try:
            import yaml
            with open(identity_path, 'w') as f:
                yaml.dump(default_identity, f, default_flow_style=False)
            self.print_success("Created default identity.yaml")
        except Exception as e:
            self.print_error(f"Failed to create identity: {e}")

    def create_default_knowledge(self):
        """Create default knowledge.yaml"""
        default_knowledge = {
            "facts": [],
            "concepts": [],
            "last_updated": datetime.now().isoformat()
        }

        knowledge_path = self.data_dir / "knowledge.yaml"
        try:
            import yaml
            with open(knowledge_path, 'w') as f:
                yaml.dump(default_knowledge, f, default_flow_style=False)
            self.print_success("Created default knowledge.yaml")
        except Exception as e:
            self.print_error(f"Failed to create knowledge: {e}")


class SetupFlowTester:
    """
    Tests the complete ARIA setup flow.
    """

    def __init__(self, project_root: str = None):
        self.project_root = Path(project_root or self._find_project_root())
        self.reset_manager = ARIAResetManager(str(self.project_root))
        self.test_results = []

    def _find_project_root(self) -> Path:
        current = Path(__file__).resolve().parent
        while current != current.parent:
            if (current / "config.yaml").exists():
                return current
            current = current.parent
        return Path.cwd()

    def print_header(self, text: str):
        self.reset_manager.print_header(text)

    def print_test(self, name: str, passed: bool, details: str = ""):
        status = f"{Colors.GREEN}PASS{Colors.ENDC}" if passed else f"{Colors.RED}FAIL{Colors.ENDC}"
        print(f"  [{status}] {name}")
        if details:
            print(f"         {Colors.DIM}{details}{Colors.ENDC}")
        self.test_results.append((name, passed, details))

    def run_setup_script_test(self, mode: str = "--check") -> bool:
        """Test the setup script"""
        setup_script = self.project_root / "scripts" / "setup_aria.py"

        if not setup_script.exists():
            return False

        try:
            result = subprocess.run(
                [sys.executable, str(setup_script), mode],
                capture_output=True,
                text=True,
                timeout=60
            )
            return result.returncode == 0 or "installed" in result.stdout.lower()
        except Exception:
            return False

    def test_python_imports(self) -> bool:
        """Test that core Python modules can be imported"""
        try:
            import yaml
            import chromadb
            import anthropic
            return True
        except ImportError:
            return False

    def test_data_directories(self) -> bool:
        """Test that data directories exist"""
        required_dirs = ["memories_v2", "coding_agent", "logs"]
        for d in required_dirs:
            if not (self.reset_manager.data_dir / d).exists():
                return False
        return True

    def test_memory_system(self) -> Tuple[bool, str]:
        """Test memory system initialization"""
        try:
            sys.path.insert(0, str(self.project_root))
            from core.memory.memory_v2 import ExperientialMemorySystem

            # Create a test instance
            test_dir = self.reset_manager.data_dir / "test_memory"
            test_dir.mkdir(exist_ok=True)

            memory = ExperientialMemorySystem(str(test_dir))

            # Cleanup
            if test_dir.exists():
                shutil.rmtree(test_dir)

            return True, "Memory system initialized successfully"
        except Exception as e:
            return False, str(e)

    def run_all_tests(self, dry_run: bool = True):
        """Run all configuration tests"""
        self.print_header("ARIA Configuration Tests")

        # Test 1: Setup script exists
        setup_exists = (self.project_root / "scripts" / "setup_aria.py").exists()
        self.print_test("Setup script exists", setup_exists)

        # Test 2: Setup script runs
        if setup_exists:
            setup_runs = self.run_setup_script_test("--check")
            self.print_test("Setup script executes", setup_runs)

        # Test 3: Python imports
        imports_ok = self.test_python_imports()
        self.print_test("Python dependencies", imports_ok,
                       "yaml, chromadb, anthropic")

        # Test 4: Data directories
        dirs_ok = self.test_data_directories()
        self.print_test("Data directories", dirs_ok)

        # Test 5: Memory system
        memory_ok, memory_msg = self.test_memory_system()
        self.print_test("Memory system", memory_ok, memory_msg)

        # Test 6: Config file
        config_ok = (self.project_root / "config.yaml").exists()
        self.print_test("Config file", config_ok)

        # Summary
        passed = sum(1 for _, p, _ in self.test_results if p)
        total = len(self.test_results)

        print(f"\n{Colors.BOLD}Results: {passed}/{total} tests passed{Colors.ENDC}")

        if passed == total:
            print(f"{Colors.GREEN}All tests passed! ARIA is ready.{Colors.ENDC}")
        else:
            print(f"{Colors.YELLOW}Some tests failed. Run setup to fix.{Colors.ENDC}")

        return passed == total


def interactive_mode():
    """Run interactive installation mode"""
    tester = SetupFlowTester()
    manager = tester.reset_manager

    manager.print_header("ARIA Setup & Reset Tool")

    print("This tool allows you to reset or repair ARIA installation.\n")
    print(f"{Colors.BOLD}Choose an option:{Colors.ENDC}\n")
    print(f"  {Colors.RED}1. FRESH INSTALL{Colors.ENDC}")
    print(f"     Delete ALL data and start from zero")
    print(f"     (Like formatting and reinstalling the OS)\n")
    print(f"  {Colors.YELLOW}2. KEEP USER DATA{Colors.ENDC}")
    print(f"     Reset system, but preserve memories and identity")
    print(f"     (Like reinstalling OS but keeping your files)\n")
    print(f"  {Colors.GREEN}3. REPAIR INSTALL{Colors.ENDC}")
    print(f"     Only reinstall dependencies, keep everything")
    print(f"     (Like repairing the OS)\n")
    print(f"  {Colors.BLUE}4. TEST ONLY{Colors.ENDC}")
    print(f"     Run tests without modifying anything\n")
    print(f"  {Colors.DIM}5. Show data summary{Colors.ENDC}")
    print(f"  {Colors.DIM}6. Exit{Colors.ENDC}\n")

    while True:
        try:
            choice = input(f"{Colors.BOLD}Enter choice [1-6]: {Colors.ENDC}").strip()

            if choice == "1":
                return InstallMode.FRESH_INSTALL
            elif choice == "2":
                return InstallMode.KEEP_USER_DATA
            elif choice == "3":
                return InstallMode.REPAIR_INSTALL
            elif choice == "4":
                return InstallMode.TEST_ONLY
            elif choice == "5":
                manager.show_data_summary()
                print()
            elif choice == "6":
                print("Exiting.")
                sys.exit(0)
            else:
                print("Please enter 1-6")
        except KeyboardInterrupt:
            print("\nCancelled.")
            sys.exit(1)


def execute_mode(mode: InstallMode, dry_run: bool = False):
    """Execute the selected installation mode"""
    tester = SetupFlowTester()
    manager = tester.reset_manager

    if mode == InstallMode.TEST_ONLY:
        tester.run_all_tests(dry_run=True)
        return

    if mode == InstallMode.FRESH_INSTALL:
        manager.print_header("FRESH INSTALL")

        # Show what will be deleted
        stats = manager.get_memory_stats()
        print(f"{Colors.RED}WARNING: This will DELETE:{Colors.ENDC}")
        print(f"  - {stats['experiential_memories']} experiential memories")
        print(f"  - {stats['relationships']} relationships")
        print(f"  - {stats['coding_memories']} coding memories")
        print(f"  - Total: {manager._format_size(stats['total_size'])}")
        print()

        if not dry_run:
            confirm = input(f"{Colors.RED}Type 'DELETE ALL' to confirm: {Colors.ENDC}")
            if confirm != "DELETE ALL":
                print("Cancelled.")
                return

            # Create emergency backup anyway
            manager.backup_user_data()

            # Reset everything
            manager.reset_all_data()
            manager.create_default_identity()
            manager.create_default_knowledge()

    elif mode == InstallMode.KEEP_USER_DATA:
        manager.print_header("RESET WITH USER DATA PRESERVED")

        stats = manager.get_memory_stats()
        print(f"{Colors.GREEN}PRESERVING:{Colors.ENDC}")
        print(f"  - {stats['experiential_memories']} experiential memories")
        print(f"  - {stats['relationships']} relationships")
        print(f"  - {stats['coding_memories']} coding memories")
        print(f"  - Identity and personality")
        print()
        print(f"{Colors.YELLOW}RESETTING:{Colors.ENDC}")
        print(f"  - System logs")
        print(f"  - Temporary files")
        print(f"  - Session data")
        print()

        if not dry_run:
            confirm = input("Continue? [y/N]: ").strip().lower()
            if confirm != 'y':
                print("Cancelled.")
                return

            # Backup user data
            manager.backup_user_data()

            # Reset only system data
            manager.reset_system_data()

    elif mode == InstallMode.REPAIR_INSTALL:
        manager.print_header("REPAIR INSTALL")
        print("Reinstalling dependencies without touching data...")
        print()

        if not dry_run:
            # Run setup script for dependencies only
            setup_script = tester.project_root / "scripts" / "setup_aria.py"
            if setup_script.exists():
                subprocess.run([sys.executable, str(setup_script), "--python"])

    # Run tests after operation
    print()
    tester.run_all_tests(dry_run=True)


def main():
    parser = argparse.ArgumentParser(
        description="ARIA Setup Flow Test & Reset Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Installation Modes:
  --fresh       Delete ALL data, complete reset (like format + reinstall)
  --keep-data   Reset system, preserve memories (like reinstall keeping files)
  --repair      Only reinstall dependencies
  --test        Run tests without modifying anything

Examples:
  python scripts/test_setup_flow.py              # Interactive mode
  python scripts/test_setup_flow.py --test       # Test only
  python scripts/test_setup_flow.py --keep-data  # Reset keeping memories
"""
    )

    parser.add_argument("--fresh", action="store_true",
                       help="Fresh install - delete all data")
    parser.add_argument("--keep-data", action="store_true",
                       help="Reset but keep user data (memories, identity)")
    parser.add_argument("--repair", action="store_true",
                       help="Repair install - only reinstall dependencies")
    parser.add_argument("--test", action="store_true",
                       help="Test only - don't modify anything")
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would happen without doing it")
    parser.add_argument("--summary", action="store_true",
                       help="Show data summary and exit")

    args = parser.parse_args()

    # Determine mode
    if args.summary:
        manager = ARIAResetManager()
        manager.show_data_summary()
        return

    if args.fresh:
        mode = InstallMode.FRESH_INSTALL
    elif args.keep_data:
        mode = InstallMode.KEEP_USER_DATA
    elif args.repair:
        mode = InstallMode.REPAIR_INSTALL
    elif args.test:
        mode = InstallMode.TEST_ONLY
    else:
        mode = interactive_mode()

    execute_mode(mode, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
