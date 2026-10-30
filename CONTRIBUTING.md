# Contributing

Thank you for wanting to improve the Social Media Factory. You don't need to be a programmer: you can
describe a change to Claude in plain words and let it do the work, as long as it follows these rules.

## The rules every change keeps

1. **It never invents.** No fact, number, quote, customer or result that doesn't trace to the brand's
   own files. If it can't be traced, it is labelled unverified and a person decides.
2. **Nothing is sent without a yes.** A preview makes no calls to anything. If a change can post,
   schedule or spend money, it says what it will do and waits.
3. **Keys stay out.** Never put a key, a password or anything from a `Client` folder (other than the
   made-up bakery) into a change, an issue or a pull request.
4. **No safety check gets weaker.** If a check is in the way, fix the cause.

## How to send a change

1. **A test that fails first.** Prove the thing is broken or missing before you fix or build it.
2. **The smallest change that fixes it.**
3. **Run all the tests** (`python -m unittest discover -s tests -t .` with the Social Media Factory's own
   Python, or ask Claude to "run all the tests").
4. **A pull request** with a plain-English description of what changed and why. One improvement per
   pull request.

A feature is a skill plus a command: the plain-English instructions Claude reads
(`.claude/skills/<name>/SKILL.md`) and the code it runs (in `smf/`, listed in `smf/cli.py`), plus one row in
`smf/features.json`. The start menu, the status screen and `GUIDE.md` are all built from that table.

## Reporting a bug

Open an issue that says what you asked for, what happened and what you expected. Say "check my setup" to
Claude first and include what it reports, with any keys or personal details removed.

Security problems go through [SECURITY.md](SECURITY.md), not an issue.
