"""dedup.py - has this brand already said this? And which old posts are fair to bring back?

Both questions are answered from ONE place: the `posts_written` table in the brand's own
Studio/registry.db. Every brand has its own file, so one brand's posts are never compared with,
or offered to, another brand.

SAYING IT AGAIN
A new draft is compared with every post the brand has written. Text is lower-cased, punctuation
is dropped, and each post becomes the set of its five-word runs. Two posts are near-duplicates
when more than 60% of those runs are shared. Short posts fall back to single words so they still
compare. One exception: the same words under a DIFFERENT identity of the same brand (the founder
and the company page) is a deliberate mirror and is reported as such, not as a repeat. That
exception only applies when the caller says who is posting; without it, any match counts.

An empty library, a missing table or a missing file means "nothing to compare". It is never an
exception: a brand that has written nothing yet is a normal brand.

BRINGING ONE BACK
A good post can return, but the feed must not feel like a rerun:
  * the same post may not come back within 14 days of its last use;
  * the same execution (topic + shape + proof) may not come back within 30 days, even as a
    different post: change the shape or the proof, or wait;
  * candidates are offered least-used first, then longest-rested first.
Uses are kept in a small `post_uses` table beside `posts_written`, so how often a post has gone
out is a count of real events rather than a number someone has to remember to bump. Each use
also notes WHICH execution went out, so a post that has since been given a new shape is judged
by what it is now, while the execution that really ran keeps resting.

    from smf.studio import dedup
    dedup.similar_posts(text, brand, identity="person").is_duplicate
    dedup.record_post(brand, post_id="w1-li-01", platform="linkedin", identity="person", text=text,
                      topic_id="flat-loaf", shape="three-tips")
    dedup.mark_used(brand, "w1-li-01")
    dedup.candidates(brand, identity="person", platform="instagram")
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from smf import brands
from smf.studio.files import StudioError, as_brand

SHINGLE_WORDS = 5
SIMILARITY_LIMIT = 0.6          # strictly above this is a near-duplicate
SAME_EXECUTION_DAYS = 30        # topic + shape + proof
SAME_POST_DAYS = 14

_USES_SCHEMA = """
CREATE TABLE IF NOT EXISTS post_uses (
    post_id   TEXT NOT NULL,
    used_at   TEXT NOT NULL,
    execution TEXT NOT NULL DEFAULT ''      -- topic|shape|proof as it was when it went out
);
CREATE INDEX IF NOT EXISTS ix_post_uses_post ON post_uses(post_id);
"""


class LibraryError(StudioError):
    """The brand's library of written posts could not be updated."""


@dataclass
class DedupResult:
    is_duplicate: bool
    exempt: bool                 # matches exist, but every one is a mirror under another identity
    matches: list = field(default_factory=list)      # [{post_id, platform, identity, similarity}]
    compared: int = 0

    def as_dict(self):
        return {"is_duplicate": self.is_duplicate, "exempt": self.exempt, "matches": list(self.matches),
                "compared": self.compared}


# ----------------------------------------------------------------------------- similarity
def _normalise(text):
    text = re.sub(r"[^\w\s']", " ", (text or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def shingles(text, k=SHINGLE_WORDS):
    words = _normalise(text).split()
    if not words:
        return frozenset()
    k = min(k, len(words))
    return frozenset(" ".join(words[i:i + k]) for i in range(len(words) - k + 1))


def similarity(a, b):
    """Share of five-word runs two texts have in common (0..1)."""
    sa, sb = shingles(a), shingles(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / float(len(sa | sb))


# ----------------------------------------------------------------------------- the library file
def _db_path(brand):
    return brand.path("Studio", "registry.db")


def _read_rows(brand, sql, args=()):
    """Run a read against the brand's library. No file, no table, damaged file: an empty answer."""
    path = _db_path(brand)
    if not os.path.isfile(path):
        return []
    try:
        con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(sql, args).fetchall()]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def _connect_for_writing(brand):
    """Open (and if needed create) the library. The tables are made if they are not there, so a
    brand whose library file was never created, or was cleared out, can still record posts."""
    path = _db_path(brand)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        con = sqlite3.connect(path)
        con.executescript(brands.REGISTRY_SCHEMA)
        con.executescript(_USES_SCHEMA)
        return con
    except sqlite3.Error as e:
        raise LibraryError("%s's library of written posts could not be opened (%s). Nothing was recorded."
                           % (brand.name, e))


def _stamp(when=None):
    when = when or datetime.now(timezone.utc)
    if when.tzinfo is not None:
        when = when.astimezone(timezone.utc).replace(tzinfo=None)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _cutoff(days, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is not None:
        now = now.astimezone(timezone.utc).replace(tzinfo=None)
    return (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _proof_list(raw):
    try:
        value = json.loads(raw or "[]")
    except ValueError:
        return []
    return [str(p) for p in value] if isinstance(value, list) else []


def execution_key(topic_id, shape, proof_ids):
    """What makes two posts 'the same execution': the subject, the structure and the evidence."""
    return "%s|%s|%s" % (topic_id or "", shape or "", ",".join(sorted(str(p) for p in (proof_ids or []))))


# ----------------------------------------------------------------------------- has this been said?
def written_posts(brand):
    """Every post in THIS brand's library, with how often and how recently each went out."""
    brand = as_brand(brand)
    rows = _read_rows(brand, "SELECT post_id, topic_id, shape, platform, identity, text, proof_ids, written_at, "
                             "used_at FROM posts_written ORDER BY written_at, post_id")
    uses = {}
    for u in _read_rows(brand, "SELECT post_id, COUNT(*) AS n, MAX(used_at) AS last FROM post_uses GROUP BY post_id"):
        uses[u["post_id"]] = (u["n"], u["last"] or "")
    for r in rows:
        r["proof_ids"] = _proof_list(r.get("proof_ids"))
        n, last = uses.get(r["post_id"], (0, ""))
        r["times_used"] = n
        r["last_used_at"] = last or (r.get("used_at") or "")
        if not n and r["last_used_at"]:
            r["times_used"] = 1                     # marked as used by a tool that does not keep the history
    return rows


def similar_posts(text, brand, identity=None, exclude_ids=(), limit=SIMILARITY_LIMIT):
    """Compare a draft with everything the brand has written. Never raises for an empty library."""
    brand = as_brand(brand)
    if identity:
        brand.identity(identity)                     # an identity this brand lacks is an error, not a guess
    mine = shingles(text)
    skip = set(exclude_ids or ())
    rows = [r for r in written_posts(brand) if r["post_id"] not in skip and (r.get("text") or "").strip()]
    matches = []
    for r in rows:
        theirs = shingles(r["text"])
        if not mine or not theirs:
            continue
        score = len(mine & theirs) / float(len(mine | theirs))
        if score > limit:
            matches.append({"post_id": r["post_id"], "platform": r["platform"], "identity": r["identity"],
                            "similarity": round(score, 4)})
    matches.sort(key=lambda m: (-m["similarity"], m["post_id"]))
    if not matches:
        return DedupResult(False, False, [], len(rows))
    mirrors_only = bool(identity) and all(m["identity"] and m["identity"] != identity for m in matches)
    return DedupResult(not mirrors_only, mirrors_only, matches, len(rows))


# ----------------------------------------------------------------------------- record and reuse
def record_post(brand, post_id, platform, identity, text, topic_id="", shape="", proof_ids=(), now=None):
    """Add a written post to the brand's library, or refresh its words. Recording the same id
    again keeps its history of uses."""
    brand = as_brand(brand)
    brand.identity(identity)
    if not str(post_id or "").strip() or not str(platform or "").strip() or not str(text or "").strip():
        raise LibraryError("A post needs an id, a platform and its text before it can be recorded.")
    with closing(_connect_for_writing(brand)) as con, con:
        con.execute(
            "INSERT INTO posts_written (post_id, topic_id, shape, platform, identity, text, proof_ids, written_at) "
            "VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(post_id) DO UPDATE SET topic_id=excluded.topic_id, shape=excluded.shape, "
            "platform=excluded.platform, identity=excluded.identity, text=excluded.text, "
            "proof_ids=excluded.proof_ids",
            (post_id, topic_id or "", shape or "", platform, identity, text,
             json.dumps([str(p) for p in (proof_ids or [])]), _stamp(now)))
    return post_id


def record(brand, post, now=None):
    """Record a Post object. A post that belongs to another brand is refused."""
    brand = as_brand(brand)
    if post.brand != brand.id:
        raise LibraryError("Post %s belongs to %s, not %s. It was not recorded." % (post.id, post.brand, brand.id))
    return record_post(brand, post.id, post.platform, post.identity, post.text, topic_id=post.topic_id,
                       shape=post.shape, proof_ids=post.proof_ids, now=now)


def mark_used(brand, post_id, when=None):
    """Note that a post went out. Returns False when the brand has no such post."""
    brand = as_brand(brand)
    with closing(_connect_for_writing(brand)) as con, con:
        row = con.execute("SELECT topic_id, shape, proof_ids FROM posts_written WHERE post_id = ?",
                          (post_id,)).fetchone()
        if row is None:
            return False
        stamp = _stamp(when)
        con.execute("INSERT INTO post_uses (post_id, used_at, execution) VALUES (?, ?, ?)",
                    (post_id, stamp, execution_key(row[0], row[1], _proof_list(row[2]))))
        con.execute("UPDATE posts_written SET used_at = (SELECT MAX(used_at) FROM post_uses WHERE post_id = ?) "
                    "WHERE post_id = ?", (post_id, post_id))
    return True


def _resting_executions(brand, rows, cut):
    """Executions that went out on or after `cut`. A use recorded here carries its own execution;
    a post another tool marked as used (no history) is taken to have gone out as it is now."""
    logged = _read_rows(brand, "SELECT post_id, used_at, execution FROM post_uses")
    resting = {u["execution"] for u in logged if u["used_at"] >= cut and u["execution"]}
    with_history = {u["post_id"] for u in logged}
    for r in rows:
        if r["post_id"] not in with_history and r["last_used_at"] and r["last_used_at"] >= cut:
            resting.add(execution_key(r["topic_id"], r["shape"], r["proof_ids"]))
    return resting


def on_cooldown(brand, topic_id, shape, proof_ids=(), within_days=SAME_EXECUTION_DAYS, now=None):
    """True when this exact topic + shape + proof went out recently. Bringing it back now would be
    a repeat; change the shape or the proof instead."""
    brand = as_brand(brand)
    return execution_key(topic_id, shape, proof_ids) in _resting_executions(brand, written_posts(brand),
                                                                            _cutoff(within_days, now))


def candidates(brand, identity, platform=None, topic_id=None, exclude_ids=(), limit=10, now=None,
               same_post_days=SAME_POST_DAYS, same_execution_days=SAME_EXECUTION_DAYS):
    """Posts that may come back for this identity, honouring both waiting periods, offered
    least-used first and then longest-rested first."""
    brand = as_brand(brand)
    brand.identity(identity)
    rows = written_posts(brand)
    post_cut = _cutoff(same_post_days, now)
    resting = _resting_executions(brand, rows, _cutoff(same_execution_days, now))
    skip = set(exclude_ids or ())
    out = []
    for r in rows:
        if r["identity"] != identity or r["post_id"] in skip:
            continue
        if platform and r["platform"] != platform:
            continue
        if topic_id and r["topic_id"] != topic_id:
            continue
        if r["last_used_at"] and r["last_used_at"] >= post_cut:
            continue
        if execution_key(r["topic_id"], r["shape"], r["proof_ids"]) in resting:
            continue
        out.append(r)
    out.sort(key=lambda r: (r["times_used"], r["last_used_at"], r["written_at"], r["post_id"]))
    return out[:limit]
