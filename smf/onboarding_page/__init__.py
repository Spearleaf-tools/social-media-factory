"""onboarding_page - onboarding on its own page, on this computer (card F5).

The page asks; Claude or Codex thinks. The page is a fixed interview served on 127.0.0.1. The agent
reads the website and drafts answers before it opens, waits on it with `onboard-page --wait`, then
builds the brand from the answers file exactly as the chat onboarding does, and hands the page the
result with `onboard-page --result`.

    session.py           the two files the page and the agent share, and who may write which
    intake.schema.json   the shape of the answers file
    secrets_check.py     deletes anything typed that looks like a key or a password
    server.py            the page's local web server
    cli.py               the `onboard-page` command
"""
