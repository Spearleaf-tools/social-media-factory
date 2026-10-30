"""batch_cli.py - from a checked draft to a batch someone can review.

    python factory.py posts add      --brand B --batch week-1 --identity person --platform linkedin --draft draft.txt
                                     [--run R --topic T] [--shape S] [--media a.png b.png] [--thread t.txt]
                                     [--alt-text "..."] [--first-comment "..."] [--link URL] [--lane evergreen]
    python factory.py posts attach   --brand B --batch week-1 --id <post id> --media 1.png 2.png
    python factory.py posts check    --brand B --batch week-1
    python factory.py posts schedule --brand B --batch week-1 [--start 2026-10-05] [--days 7]
    python factory.py posts list     --brand B [--batch week-1]

A batch lives in the brand's Output/batches/ folder. `add` runs the full draft check first
(rules, facts, repeats, takeaway) and records the verdict on the post: sourcing is `passed`,
`unverified` or `blocked`, never assumed. The check reads every field that would publish
together, the first comment and the alt text included, so a claim cannot arrive in one of them
after the caption has been cleared. A draft with problems is refused with the reasons; use
--allow-problems to file it as a draft anyway so it can be fixed on the review page.

`attach` reads what the Factory recorded about the words drawn INSIDE each picture. A picture
claim its files cannot confirm makes the whole post unverified, because a reader does not care
which part of a post a number was written on.
Nothing here sends anything anywhere.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time

from smf import brands
from smf.studio import posts as P


def _batch_path(brand, name):
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,60}$", name or ""):
        raise brands.BrandError("a batch name is short and simple, for example week-1")
    if not name.endswith(".json"):
        name += ".json"
    return brand.path("Output", "batches", name)


def _load(brand, name):
    path = _batch_path(brand, name)
    if os.path.isfile(path):
        posts, meta = P.load_batch(path, brand.id)
    else:
        posts, meta = [], {"created": time.strftime("%Y-%m-%d %H:%M:%S")}
    return path, posts, meta


def _media(brand, paths):
    """Store media as paths relative to the brand folder when they are inside it. A file that
    does not exist is refused now, not at posting time."""
    out = []
    home = os.path.abspath(brand.home) + os.sep
    for m in paths or []:
        full = os.path.abspath(m if os.path.isabs(m) else os.path.join(os.getcwd(), m))
        if not os.path.isfile(full):
            alt = brand.path(*m.replace("\\", "/").split("/"))
            if os.path.isfile(alt):
                full = os.path.abspath(alt)
            else:
                raise brands.BrandError("that picture or video could not be found: %s" % os.path.basename(m))
        out.append(full[len(home):].replace(os.sep, "/") if full.startswith(home) else full)
    return out


def _read(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read().strip()


def _new_id(brand, platform, identity, text, existing):
    base = hashlib.sha256(("%s|%s|%s|%s" % (brand.id, identity, platform, text)).encode("utf-8")).hexdigest()[:8]
    pid, n = "%s-%s" % (platform[:2], base), 1
    while pid in existing:
        n += 1
        pid = "%s-%s-%d" % (platform[:2], base, n)
    return pid


def cmd_add(a, brand):
    from smf.studio import contract, dedup, topics as topics_mod
    text = _read(a.draft)
    thread = [seg.strip() for seg in re.split(r"\n\s*---+\s*\n", _read(a.thread)) if seg.strip()] if a.thread else []
    topic = topics_mod.get_topic(brand, a.run, a.topic) if (a.run and a.topic) else {}
    if (a.run or a.topic) and not topic:
        raise brands.BrandError("name both the run and the topic, or neither")
    path, posts, meta = _load(brand, a.batch)
    media = _media(brand, a.media)
    pid = _new_id(brand, a.platform, a.identity, text, {p.id for p in posts})
    report = contract.validate_draft(text, brand, a.identity, a.platform, topic, thread=thread, post_id=pid,
                                     first_comment=a.first_comment or "", alt_text=a.alt_text or "",
                                     link=a.link or "")
    print(contract.format_report(report))
    if not report["ok"] and not a.allow_problems:
        print("\nNot added. Fix the draft and add it again, or use --allow-problems to file it as a draft to fix later.")
        return 1
    post = P.Post(id=pid, brand=brand.id, identity=a.identity, platform=a.platform, text=text, media_paths=media,
                  thread=thread, topic_id=(topic.get("id") or a.topic or ""), shape=a.shape or "",
                  pillar=topic.get("pillar", "") if topic else "", lane=a.lane or (topic.get("lane") if topic else "") or "evergreen",
                  proof_ids=list(topic.get("proof_ids") or []) if topic else [], alt_text=a.alt_text or "",
                  first_comment=a.first_comment or "", link=a.link or "", media_type=a.media_type or "")
    contract.apply_to_post(post, report)
    for line in _fold_in_picture_claims(brand, post):
        print(line)
    posts.append(post)
    P.check_batch(posts, brand)
    P.save_batch(posts, path, meta)
    try:
        dedup.record(brand, post)
    except Exception:                                   # the library is a convenience; never lose a post over it
        pass
    print("\nAdded to the batch '%s' as %s (%s, sourcing: %s)." % (a.batch, pid, post.status.replace("_", " "), post.sourcing))
    return 0


NOT_OURS = ("The words inside %s were not checked, because it was not drawn here. Read them yourself before this "
            "goes out.")


def _picture_report(brand, rel):
    """What the Factory recorded about the picture at `rel`, or None when it drew no such picture.
    The record sits beside the file, so a picture that was moved or made elsewhere has none."""
    from smf.studio.render import REPORT_NAME
    full = rel if os.path.isabs(rel) else brand.path(*rel.replace("\\", "/").split("/"))
    beside = os.path.join(os.path.dirname(full), REPORT_NAME)
    if not os.path.isfile(beside):
        return None
    try:
        with open(beside, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("brand") != brand.id:
        return None
    name = os.path.basename(full)
    return next((e for e in data.get("picture_claims") or [] if e.get("file") == name), None)


def _fold_in_picture_claims(brand, post):
    """Check the words drawn inside this post's pictures and fold the answer into its sourcing.

    A reader does not care which part of a post a claim was written on, so an unconfirmed claim
    in a picture leaves the whole post unverified. The claims are checked again here, against the
    brand's files as they stand now, so adding the missing fact and attaching again is enough."""
    from smf.studio import grounding
    notes, verdict, corpus = [], "passed", None
    for rel in post.media_paths:
        entry = _picture_report(brand, rel)
        if entry is None:
            notes.append(NOT_OURS % os.path.basename(str(rel)))
            continue
        if corpus is None:                                  # only read the brand's files if a picture claims something
            corpus = grounding.build_corpus(brand, post.proof_ids)
        for claim in grounding.check_drawn_text(brand, entry.get("texts") or [], source=entry.get("source") or "",
                                                proof_ids=post.proof_ids, corpus=corpus):
            if not claim["confirmed"]:
                verdict = "unverified"
                notes.append("%s shows \"%s\", and nothing in %s's files confirms it. Record the fact with its "
                             "source, or change the picture."
                             % (entry.get("slide") or os.path.basename(str(rel)), claim["phrase"], brand.name))
    post.facts_check = dict(post.facts_check or {}, pictures=verdict, picture_notes=notes,
                            media=list(post.media_paths))
    P.settle_sourcing(post)
    return notes


def cmd_attach(a, brand):
    path, posts, meta = _load(brand, a.batch)
    hit = [p for p in posts if p.id == a.id]
    if not hit:
        raise brands.BrandError("the batch '%s' has no post with the id %s" % (a.batch, a.id))
    post = hit[0]
    if post.status in ("scheduled", "posted", "exported"):
        raise brands.BrandError("that post has already gone out or been exported, so it is not changed")
    post.media_paths = _media(brand, a.media) if a.replace else post.media_paths + _media(brand, a.media)
    if post.approved_at and not P.approval_is_current(post):
        post.approved_at, post.approved_text_sha, post.status = "", "", "lint_pass"
        print("The pictures changed after it was approved, so it needs approving again.")
    notes = _fold_in_picture_claims(brand, post)
    P.check_batch(posts, brand)
    P.save_batch(posts, path, meta)
    print("%s now has %d picture(s) or video(s)." % (post.id, len(post.media_paths)))
    for line in notes:
        print("  " + line)
    if post.sourcing != "passed":
        print("The post is marked %s until that is sorted out." % post.sourcing)
    return 0


def cmd_check(a, brand):
    path, posts, meta = _load(brand, a.batch)
    rep = P.check_batch(posts, brand)
    P.save_batch(posts, path, meta)
    print("%d posts: %d ready for review, %d need fixing." % (rep["total"], rep["clean"], rep["blocked"]))
    for p in posts:
        for e in p.lint_errors:
            print("  %s (%s/%s): %s" % (p.id, p.identity, p.platform, e))
    return 0 if not rep["blocked"] else 1


def cmd_schedule(a, brand):
    path, posts, meta = _load(brand, a.batch)
    if not posts:
        raise brands.BrandError("the batch '%s' is empty" % a.batch)
    movable = [p for p in posts if p.status not in ("scheduled", "posted", "exported")]
    cal = P.assign_drip_slots(movable, brand, start_date=a.start, days=a.days)
    P.assert_drip(posts)
    for p in movable:
        if p.approved_at and not P.approval_is_current(p):
            p.approved_at, p.approved_text_sha, p.status = "", "", "lint_pass"
    P.save_batch(posts, path, meta)
    print("Planned across %d day(s). One subject, one account per day; nothing repeats." % cal["span_days"])
    for day, entries in cal["calendar"].items():
        print("\n%s" % day)
        for e in entries:
            print("  %s  %-10s %-10s %s" % (e["time"], e["platform"], e["identity"], e["topic_id"] or e["id"]))
    if cal["overflow"]:
        print("\n%d post(s) fall after the %d-day window you asked for." % (len(cal["overflow"]), a.days))
    print("\nNothing has been sent. These are planned times only.")
    return 0


def cmd_list(a, brand):
    folder = brand.path("Output", "batches")
    names = [a.batch] if a.batch else sorted(f[:-5] for f in (os.listdir(folder) if os.path.isdir(folder) else [])
                                             if f.endswith(".json") and not f.startswith("."))
    if not names:
        print("No batches yet.")
        return 0
    for name in names:
        _path, posts, _meta = _load(brand, name)
        by = {}
        for p in posts:
            by[p.status] = by.get(p.status, 0) + 1
        print("%s: %d posts (%s)" % (name, len(posts), ", ".join("%d %s" % (n, s.replace("_", " ")) for s, n in sorted(by.items())) or "empty"))
        if a.batch:
            for p in posts:
                print("  %-14s %-9s %-10s %-10s %-16s %s" % (p.id, p.platform, p.identity, p.status, p.scheduled_time_local or "-",
                                                             (p.text or "").splitlines()[0][:60] if p.text else ""))
    return 0


def main(args):
    ap = argparse.ArgumentParser(prog="factory.py posts")
    sub = ap.add_subparsers(dest="action", required=True)
    add = sub.add_parser("add")
    attach = sub.add_parser("attach")
    check = sub.add_parser("check")
    schedule = sub.add_parser("schedule")
    lst = sub.add_parser("list")
    for p in (add, attach, check, schedule, lst):
        p.add_argument("--brand", required=True)
    for p in (add, attach, check, schedule):
        p.add_argument("--batch", required=True)
    lst.add_argument("--batch")
    add.add_argument("--identity", required=True)
    add.add_argument("--platform", required=True)
    add.add_argument("--draft", required=True, help="a text file holding the post")
    add.add_argument("--thread", help="a text file of the following tweets, separated by a line of ---")
    add.add_argument("--run")
    add.add_argument("--topic")
    add.add_argument("--shape")
    add.add_argument("--lane", choices=("evergreen", "news", "opinion"))
    add.add_argument("--media", nargs="*", default=[])
    add.add_argument("--media-type", choices=("reel", "story", "video"))
    add.add_argument("--alt-text")
    add.add_argument("--first-comment")
    add.add_argument("--link")
    add.add_argument("--allow-problems", action="store_true")
    attach.add_argument("--id", required=True)
    attach.add_argument("--media", nargs="+", required=True)
    attach.add_argument("--replace", action="store_true")
    schedule.add_argument("--start", help="first day, YYYY-MM-DD (default: tomorrow)")
    schedule.add_argument("--days", type=int)
    a = ap.parse_args(args)
    try:
        brand = brands.load(a.brand)
        return {"add": cmd_add, "attach": cmd_attach, "check": cmd_check, "schedule": cmd_schedule,
                "list": cmd_list}[a.action](a, brand)
    except (brands.BrandError, ValueError, OSError, P.DripError) as e:
        print(str(e))
        return 1
    except Exception as e:                              # the writing engine's own plain errors
        if e.__class__.__name__.endswith("Error"):
            print(str(e))
            return 1
        raise
