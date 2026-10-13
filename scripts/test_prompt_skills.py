#!/usr/bin/env python3
"""
Test prompt skill loader - verify YAML skills load and execute correctly.
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

assert os.environ.get("DEEPSEEK_API_KEY"), "set DEEPSEEK_API_KEY before running"

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
INFO = "\033[96mINFO\033[0m"

results = {"pass": 0, "fail": 0}


def test(name, func):
    try:
        ok = func()
        if ok:
            print(f"  [{PASS}] {name}")
            results["pass"] += 1
        else:
            print(f"  [{FAIL}] {name}")
            results["fail"] += 1
    except Exception as e:
        print(f"  [{FAIL}] {name}: {e}")
        results["fail"] += 1


def main():
    print("\n" + "=" * 60)
    print("  Prompt Skill Loader Tests")
    print("=" * 60)

    # Test 1: Load skills from YAML
    print(f"\n  --- Loading ---")
    from core.skills.base import SkillRegistry
    from core.skills.prompt_skill_loader import load_prompt_skills, DynamicPromptSkill

    registry = SkillRegistry()
    skills_dir = os.path.join(PROJECT_ROOT, "core", "skills")
    loaded = load_prompt_skills(skills_dir, registry)

    test("YAML skills found", lambda: len(loaded) > 0)
    print(f"  [{INFO}] Loaded {len(loaded)} skills: {[s.name for s in loaded]}")

    # Test 2: All skills have required fields
    print(f"\n  --- Validation ---")
    for skill in loaded:
        test(f"{skill.name}: has name", lambda s=skill: bool(s.name))
        test(f"{skill.name}: has description", lambda s=skill: bool(s.description))
        test(f"{skill.name}: has prompt_template", lambda s=skill: bool(s.prompt_template))
        test(f"{skill.name}: is DynamicPromptSkill", lambda s=skill: isinstance(s, DynamicPromptSkill))
        test(f"{skill.name}: registered in registry", lambda s=skill: s.name in registry)

    # Test 3: Registry integration
    print(f"\n  --- Registry ---")
    test("Registry has all loaded skills", lambda: all(s.name in registry for s in loaded))
    test("get_prompt_section includes YAML skills", lambda: all(
        s.name in registry.get_prompt_section() for s in loaded
    ))

    # Test 4: Execute one skill with DeepSeek
    print(f"\n  --- Live Execution (DeepSeek) ---")
    from core.skills.base import SkillContext
    from core.llm.llm_providers import LLMProvider

    try:
        llm = LLMProvider.create("deepseek")
        print(f"  [{INFO}] DeepSeek LLM initialized")

        ctx = SkillContext(llm=llm)

        # Test translate skill
        translate = registry.get("translate")
        if translate:
            result = translate.execute("translate 'buenos días, cómo estás?' to English", ctx)
            test("translate skill executes", lambda: result.success)
            if result.success:
                print(f"  [{INFO}] Output: {result.output[:100]}")

        # Test brainstorm skill
        brainstorm = registry.get("brainstorm")
        if brainstorm:
            result = brainstorm.execute("name ideas for an AI assistant", ctx)
            test("brainstorm skill executes", lambda: result.success)
            if result.success:
                lines = result.output.strip().split("\n")
                print(f"  [{INFO}] Output: {lines[0][:100]}... ({len(lines)} lines)")

        # Test sql_helper skill
        sql = registry.get("sql_helper")
        if sql:
            result = sql.execute("find all users who haven't logged in for 30 days", ctx)
            test("sql_helper skill executes", lambda: result.success)
            if result.success:
                print(f"  [{INFO}] Output: {result.output[:100]}...")

    except Exception as e:
        print(f"  [{FAIL}] LLM init failed: {e}")
        results["fail"] += 1

    # Summary
    print(f"\n{'='*60}")
    total = results["pass"] + results["fail"]
    print(f"  Total: {total}  Passed: {results['pass']}  Failed: {results['fail']}")
    print(f"{'='*60}\n")

    sys.exit(0 if results["fail"] == 0 else 1)


if __name__ == "__main__":
    main()
