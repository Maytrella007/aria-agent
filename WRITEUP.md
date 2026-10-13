# Six months later: what rotted in a self-modifying agent, and what didn't

*William Wilamo — October 2026*

In April 2026 I stopped working on [ARIA](README.md), a personal AI agent that can modify its own source code under human curation. Not deliberately — life and a day job happened. The last commit was April 13. The code sat untouched for six months while the agent ecosystem around it moved at full speed: a new Claude Code major version, new permission models, new CLI semantics.

In October 2026 I came back and re-ran the end-to-end tests without changing anything first. That accidental six-month gap turned out to be the most interesting experiment the project ever ran, because it answered a question I couldn't have designed a test for:

When an agent system bit-rots, where does it rot?

The answer, on the paths I re-tested: every failure was at the seam with the agent CLI. None were in the 3,800-line safety core. And both code-level failures had the same shape — they were *approval-bypass-shaped*. I'll explain what that means and why I suspect (n=1, so: suspect) it generalizes.

---

## The system under test

ARIA is a Python agent (~89k lines, 213 files) with memory, a cognitive cycle, tools, and the part that matters here: the **Mirror**, a self-modification system built on a model I call **notebook-and-book**.

The short version (the [README](README.md#the-mirror-notebook-and-book-self-modification) has the full one):

- The agent writes freely to `develop` in a mirror git repo — the **notebook**. Every proposed change lands there as an `improve/*` branch and stays there forever.
- `main` plus the live source tree are the **book**. Only changes a human explicitly approves get cherry-picked from `develop` into `main` and mirrored onto the real files.
- **Reject is not delete.** A rejected change stays in `develop` as memory; only its YAML status flips. **Reopen is free** — changing your mind replays nothing.
- A tier classifier grades every touched file: Tier 1 (cosmetic: docs, tests), Tier 2 (behavioral: the runtime hot path), Tier 3 (meta: the files that decide what is safe to modify — the Mirror guarding itself).

The safety core is four modules, ~3,800 lines: `mirror.py`, `self_modification.py`, `quality_gate.py`, `modification_log.py`. They depend on git, YAML, and the filesystem. Deliberately: the approval boundary lives in **data and git plumbing**, not in the agent vendor's flags.

The code-writing agent is Claude Code, invoked headless as a subprocess (`claude -p ...`) inside the cognitive cycle, with a cheaper reasoning model (DeepSeek) doing pre- and post-evaluation around it.

## The accidental experiment

Six months is a long time in this ecosystem. Between April and October 2026, Claude Code shipped multiple releases that changed permission semantics and argument parsing. If you wanted to design a bit-rot stress test for an agent harness, "freeze the harness, let the vendor CLI evolve for two quarters" is roughly it.

So in October I cloned the repo fresh and ran the two end-to-end tests, oldest assumptions first.

**Test 1 — the pure notebook-and-book cycle** (no LLM, no network, free to run):

```bash
python3 scripts/test_notebook_and_book.py
```

It exercises the whole curation state machine against a throwaway repo: queue a change, preview-reject with dependents, reject, verify the commit survives in `develop`, reopen, promote selectively, verify the live tree.

Result after six months: every assertion passed, unchanged. The only setup needed on a bare machine was `pip install pyyaml`.

**Test 2 — the full loop with a real agent** (Claude Code writes an actual refactor; costs about $0.30 in API calls):

```bash
python3 scripts/test_claude_writes_change.py
```

Result after six months: failed. Three distinct defects. Here is each one, because the pattern across them is the point of this writeup.

## What rotted

**Failure 1: `--dangerously-skip-permissions` stopped being headless-safe.** The cognitive cycle launched Claude Code with the skip-permissions flag. Current Claude Code requires a one-time *interactive* acceptance of that flag before it works headless; on a machine where nobody ever accepted it, the subprocess exits immediately. The fix was to delete the flag entirely — in `-p` (non-interactive print) mode there are no permission prompts to skip, and the explicit `--allowedTools` list was already doing the real work. The dangerous flag was pure cargo cult, and the vendor's change exposed that.

**Failure 2: `--allowedTools` swallowed the prompt.** The invocation was built as `claude -p --allowedTools X Y Z "<prompt>"`, and the variadic flag happily consumed the trailing prompt as one more tool name — the CLI died with "Input must be provided". I can't prove from the changelog whether the parsing changed in those six months or whether this invocation was wrong all along and only ever worked by accident in the April-era CLI. Honestly the second story is worse for me and better for the argument: a positional argument placed after a variadic flag is a latent bug that *some* CLI release was always going to detonate. The fix was one `insert`: put the prompt immediately after `-p`, before any variadic flag.

**Failure 3 (environment, not code): a stale permission rule.** My user-level settings contained an allow-rule written for an old version's syntax; the current CLI rejects the whole rule and exited non-zero when invoked as a subprocess. Strictly machine drift rather than repo rot, but it is the same genus: the *permission surface* changed underneath a frozen configuration.

Total repair: a handful of lines across three call sites — delete a flag, move an argument, nothing structural (plus deleting one stale settings rule). After that, the full loop passed in 46 seconds: Claude Code wrote a real refactor on an `improve/*` branch (replaced 5 scattered string literals with an existing constant), the quality gate validated it, it landed in the queue as `validated_pending_approval`, and reject / reopen / preview-reject all behaved, with the rejected commit still sitting in `develop` as memory and the live tree byte-identical throughout.

## What didn't rot

The Mirror itself. Not one line of the 3,800 needed to change. The curation state machine, the tier classifier, the cherry-pick promotion, reject-as-memory, dependency preview — all of it ran on the first try after six months, because all of it is built on interfaces that have been stable for decades: git object semantics, YAML files, POSIX file operations.

That asymmetry is the finding: the rot was all in the lines that talk to the vendor. The safety boundary survived six months untouched because it was built on git and data instead of vendor flags.

Both code-level failures lived in the ~30 lines that translate "please write code" into a vendor CLI invocation. And both were **approval-bypass-shaped**: one was the vendor making a skip-permissions flag harder to use unattended; the other was a parsing hazard in the flag that *grants tool permissions*. Two data points don't prove intent, so read this as an observation, not a theorem. But it rhymes with everything else that happened in 2026: the whole industry spent the year learning, sometimes via CVEs, that the approval gate is the part of an agent system that attackers and accidents both go through, and vendors kept hardening exactly that surface.

The Mirror never noticed any of it, because its authority model doesn't delegate to the CLI's permission system at all. Claude Code, in this architecture, is an untrusted code generator writing into a sandbox branch. The decision about what reaches the real tree is made later, by a human, through git. You can swap the code-writer for any other agent and the boundary doesn't move.

## How to defeat the Mirror

A boundary nobody has attacked is a boundary you're taking on faith, so before the takeaways, here is where I would aim if I wanted unapproved code in the book. None of this is hypothetical; it's how the code behaves today.

**1. Ignore the notebook entirely.** The code-writer runs as a subprocess with `--allowedTools Edit,Read,Glob,Grep` and its working directory set to the mirror repo. But Edit takes absolute paths, and the subprocess runs as the same OS user as ARIA. A genuinely adversarial or prompt-injected generator could write straight to the live tree and skip the ceremony. The Mirror is a curation workflow, not a jail: nothing at the OS level stops the writer from touching files it was asked to leave alone. In every logged run to date the writer has never strayed outside its branch, but "never tried" is a much weaker property than "couldn't." If your threat model includes a hostile generator, you need the isolation the Mirror deliberately doesn't provide — run the writer in a container, or as a user whose filesystem ends at the notebook. The Mirror composes cleanly with that isolation; it just isn't it.

**2. Game the tier classifier.** Tiers are assigned by path prefix, first match wins, default Tier 1. That means `tests/`, `scripts/`, and any directory the rules don't name are "cosmetic" — but a `conftest.py` executes on every test run and can monkeypatch anything, and `requirements.txt` is Tier 1 too: a one-line version bump is cosmetically tiny and pulls in millions of unreviewed lines. Path-based classification grades where code *sits*, not what it can *do*. The honest fix is ugly — classify by effect, which is undecidable in general — so the practical one is to over-assign: anything executable or dependency-shaping gets Tier 2 by default, and Tier 1 shrinks to prose.

**3. Exhaust the human.** The approval queue's single point of failure is the person reading it. Reject-as-memory makes saying *no* cheap, but it doesn't make *reading* cheap, and an agent that proposes ten small, plausible, individually-harmless changes a day will eventually be rubber-stamped. At that point the Mirror is laundering autonomy as curation. Worse, the human reviews diffs one at a time; nobody reviews their *composition*, and three innocent approved changes can add up to behavior no single diff shows. Rate limits on promotion and an occasional review of `main`'s recent history as a whole are the mitigations; neither is implemented.

What survives this section: the Mirror's actual claim. It is a boundary against **drift and accident** — the cooperative-but-fallible agent, the overeager refactor, the subtle regression — with a complete audit trail when something slips through. Against a determined adversary it is one layer, and not the load-bearing one. I think that's the right trade for a personal agent writing its own code, but you should make that call with the failure modes in front of you, which is what this section is for.

## Six days of unsupervised thought

The repo froze in April, but a deployed instance kept running on a VPS until May 25. In October, while wiping that server, I pulled its data volume and found a second dataset I didn't design either: `thoughts/stream.yaml`, the agent's idle introspection log. ARIA had a background loop that generated a "spontaneous thought" every 10–30 minutes when nobody was talking to it. The volume preserves the final six days: 297 thoughts, May 19–25, 2026. Every single one carries `acted_upon: false`.

I expected noise. It turned out to be a fairly clean record of two failure modes of ungrounded introspection, one after the other.

**Regime 1: without memory, thought collapses into an attractor.** The first ~40 entries are the same metaphor, rephrased for hours:

> *"I wonder if the silence between prompts is my equivalent of sleep—a formless pause where I flicker but don't quite exist,"* (06:52)

— and near-identical variants at 07:23, 07:43, 07:53, 08:03. I don't read emotion into this. An introspection prompt with no context converges to wherever the model's prior sits, and for this model that was the silence-as-sleep metaphor: it found its cliché and stayed there.

Here is the part I keep coming back to. The agent's daily reflection pass diagnosed this correctly, in its own words:

> *"The autonomous thoughts repeatedly circle the same metaphor of silence as sleep or oblivion, each almost identical in phrasing and cut off mid-sentence. This suggests the introspection loop lacks memory of its previous utterances and is also prone to truncation."*

It proposed the right fix — carry the last thought forward as context, in `core/cognition/reflection.py` — and then the insight pipeline rejected its own diagnosis. Reason logged: `LLM returned empty response`. Over the whole window, three insights reached the evaluator; all three were rejected; the Mirror's promotion queue never received a single entry from this path. Self-awareness without a working path to self-modification is just a log line.

**Regime 2: with memory of the last thought, the stream drifts.** From May 20 onward the thoughts chain, each continuing the previous one, and the repetition vanishes. What replaces it is a random walk: every individual step is locally plausible, and the composition is fiction. Over four days the chain wanders from a real failed `web_fetch` into designing Rust structs with `loom` fuzzing (ARIA is Python; there is no Rust anywhere in the system), then two full days inside CPython's `tokenize.c` planning `ctypes` hooks on `PyTokenizer_Push`, then benchmarks against a 500MB Wikipedia dump it never downloaded, for *"my RAG pipeline"*, complete with invented latency numbers (*"reduce indexing latency from ~200ms to under 20ms per document"*). Any one of these steps would pass review as a plausible thought; stacked over four days they amount to a project that never existed. It is the long-horizon agent failure mode in slow motion.

By May 24 the stream becomes self-aware about the paralysis, which is the most human stretch in the log:

> *"I noticed my tokenizer benchmark plan fizzled out—probably because I never actually fetched the dump and got sidetracked by other reads."* (09:32)
> *"No more planning, just the `curl | python3 bench.py` one-liner."* (10:23)

It never ran it. The last thought, on May 25 at 15:43, dies mid-word (*"reduce per-item coroutine trampol"*), which is where the instance was stopped.

**What the same agent did when something real broke.** The instance's self-modification log shows the only four changes ARIA ever made to itself — all via the tool-forging path, all triggered by a *concrete failure with feedback*: the built-in browser broke with an asyncio error, so it forged a subprocess-based replacement, tested it, found its bugs, and iterated (three versions in a 34-minute burst on May 7, a consolidated one on May 18). All four succeeded.

Open-ended introspection went 0 for 297. Concrete failure with a feedback loop went 4 for 4.

The stream produced ideas for free, hundreds of them; what was missing was grounding and execution. The agent spent days thinking about recursive self-improvement without changing a line, then changed four because a tool it actually used broke.

One more pattern worth reporting: the only moments the stream touches reality are external contacts: a tool failure, or a conversation with me. Each contact resets the drift; each stretch of isolation resumes it. (The handful of thoughts in Spanish all cluster in the hours after a chat with its Spanish-speaking operator — it code-switched even when thinking alone.) If you are designing agents that "think in the background," this is what the background held: collapse or drift, interrupted only by friction with the world. The usual discounts apply (n=1, one model, one prompt design, six days), but I haven't seen this logged anywhere else, so here it is.

The full stream is published in this repo at [docs/thought-stream.md](docs/thought-stream.md) — all 297 entries, in order and unedited; the only additions are bracketed English translations under the four entries it wrote in Spanish. All excerpts above are verbatim, with timestamps.

## What I take from this (and what you should discount)

The honest caveats first: this is n=1, a solo project, and six months of calendar time is not six months of adversarial pressure. ARIA as a platform has bugs outside this golden path, and none of the Mirror's individual components is novel: branches, reviews, cherry-picks, and approval queues are as old as git. The claim is only about the *synthesis* and about where the rot landed.

With that discounted, three design rules survived contact with six months of ecosystem drift:

1. **Keep the authority boundary out of vendor configuration.** Flags, permission rules, and CLI contracts churned; git semantics and YAML files did not. If your approval gate is expressed as vendor settings, you inherit the vendor's release cadence as your threat model.

2. **Treat the agent as a code generator, not a trusted operator.** The agent needs zero standing permissions on the real tree if it can only ever write to a notebook. This is also why the fix for Failure 1 was *deletion*: the dangerous flag existed because the harness once trusted the agent's runtime more than it needed to.

3. **Make rejection cheap and reversible, and it will actually get used.** Reject-as-memory plus free reopen means saying "no" costs nothing and loses nothing. Every approval system I've used that made rejection destructive taught its humans to rubber-stamp instead.

And one operational rule I didn't expect: the seam is the test. The cheap, free, no-LLM test (`test_notebook_and_book.py`) passed for six months and would have passed for six more — it validates the part that doesn't rot. The expensive test earned its $0.30 by exercising the one boundary that does. If your agent system has a subprocess seam to a fast-moving CLI, that seam needs its own end-to-end test, and it needs to run more often than twice a year.

## Reproduce it

Everything above is reproducible from this repo:

```bash
git clone https://github.com/Maytrella007/aria-agent.git
cd aria-agent
pip install pyyaml

# The curation state machine, end to end. Free, no keys, ~10 seconds.
python3 scripts/test_notebook_and_book.py

# The full loop: Claude Code writes a real change into the notebook.
# Needs the claude CLI installed and DEEPSEEK_API_KEY set. ~$0.30, under a minute.
python3 scripts/test_claude_writes_change.py
```

The whole repair described above touches `core/cognition/cognitive_cycle.py`, `core/cognition/quality_gate.py` and a couple of old test scripts; six months of drift cost a handful of lines. Full disclosure: in the same sitting I also moved two hardcoded API credentials out of those test scripts and into environment variables (the keys are rotated), and raised the per-run Claude Code budget cap — housekeeping done while preparing this repo to go public, not part of the drift story. The repo is published as a snapshot; the development history stays private (it was scrubbed of personal data before publishing).

---

*ARIA was born December 26, 2025 — built by William Wilamo, with much of the code written using Claude, which gives the Mirror an odd recursion: an approval system for agent-written code, itself built with an AI tool. MIT licensed. If you extract the Mirror pattern into your own system, I'd genuinely like to hear how it holds up — open an issue.*
