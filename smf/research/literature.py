"""literature.py - find published research on a question. No key, no cost.

Two public services, both free:

    PubMed (the US National Library of Medicine's index)   always used. Needs nothing.
    Unpaywall (finds a legal free copy of a paper)         used ONLY when the person gives a
                                                           contact email, because that service
                                                           asks every caller for one.

About that email. It is the PERSON'S OWN, given by them for this run. There is no built-in
address and there never will be: a made-up or shared address would be claiming to be someone.
It is sent to the two services as a courtesy contact, it is not written into the saved files,
and leaving it out simply skips the free-copy lookup.

WHAT THIS IS FOR, AND WHAT IT IS NOT
It finds papers and lays out what each abstract says, so a claim can be traced to something real
or dropped. It does not judge the science, and an abstract is not the paper. So:

  * every paper is saved as `unverified` until a person has opened and read it;
  * the kind of study is shown (a trial, a review, a single case) because they are not equal,
    but it is read from PubMed's own labels, not inferred, and "not labelled" is an answer;
  * for a brand in a regulated field, nothing here is permission to make a claim. It goes
    through that brand's sign-off like everything else.

Only lookups are made here, never a write, so the transport is built to allow nothing else.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET

from smf.research import store
from smf.research.apify import Transport, _HttpProblem

JOB = "papers"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
UNPAYWALL = "https://api.unpaywall.org/v2"
TOOL = "social-media-factory"
PAUSE = 0.4                 # the index asks keyless callers to stay under three requests a second
MAX_PAPERS = 50
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

# PubMed's own publication-type labels, strongest kind of evidence first. First match wins.
STUDY_KINDS = [("Meta-Analysis", "meta-analysis"), ("Systematic Review", "systematic review"),
               ("Randomized Controlled Trial", "randomised controlled trial"),
               ("Clinical Trial", "clinical trial"), ("Observational Study", "observational study"),
               ("Review", "review"), ("Case Reports", "case report"), ("Editorial", "editorial or comment"),
               ("Comment", "editorial or comment"), ("Letter", "editorial or comment")]


def check_email(email):
    """Returns the email, or None when none was given. A malformed one is an error, not a silent skip."""
    email = (email or "").strip()
    if not email:
        return None
    if not _EMAIL.match(email):
        raise store.ResearchError("That does not look like an email address. Give your own contact email, or leave "
                                  "it out to skip the free-copy lookup.")
    return email


def _get(transport, url, params):
    try:
        _status, _headers, raw = transport.request("GET", url + "?" + urllib.parse.urlencode(params), timeout=45)
    except _HttpProblem as p:
        if p.status == 429:
            raise store.ResearchError("The research index asked us to slow down. Wait a minute and try again.")
        if p.status == 0:
            raise store.ResearchError("Could not reach the research index. Check the internet connection.")
        raise store.ResearchError("The research index had a problem (HTTP %d). Try again in a few minutes." % p.status)
    return raw


def kind_of_study(publication_types):
    for label, plain in STUDY_KINDS:
        if any(label.lower() == str(t).lower() for t in publication_types):
            return plain
    return "not labelled"


def parse_articles(xml_bytes):
    """PubMed's XML -> a list of plain dicts. Pure."""
    text = xml_bytes.decode("utf-8", "replace") if isinstance(xml_bytes, bytes) else str(xml_bytes)
    if "<!ENTITY" in text:                     # the real service never sends one; refuse rather than expand it
        raise store.ResearchError("The research index sent something unexpected, so it was not read.")
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        raise store.ResearchError("The research index sent something unreadable. Try again in a few minutes.")
    out = []
    for art in root.findall(".//PubmedArticle"):
        cite = art.find("MedlineCitation")
        body = cite.find("Article") if cite is not None else None
        if body is None:
            continue
        pmid = (cite.findtext("PMID") or "").strip()
        parts = []
        for node in body.findall("Abstract/AbstractText"):
            piece = "".join(node.itertext()).strip()
            if piece:
                parts.append("%s: %s" % (node.get("Label").title(), piece) if node.get("Label") else piece)
        authors = [("%s %s" % (a.findtext("LastName") or "", a.findtext("Initials") or "")).strip()
                   for a in body.findall("AuthorList/Author") if a.findtext("LastName")]
        when = body.find("Journal/JournalIssue/PubDate")
        year = ""
        if when is not None:
            year = (when.findtext("Year") or "").strip() or (re.findall(r"\d{4}", when.findtext("MedlineDate") or "")
                                                             or [""])[0]
        # The paper's OWN ids live in PubmedData/ArticleIdList. The same record also lists the ids of every
        # paper it CITES, deeper down. Searching the whole record for "a DOI" would hand a paper with no DOI
        # of its own the DOI of something in its reference list: a wrong link on a citation.
        own = {i.get("IdType"): (i.text or "").strip() for i in art.findall("PubmedData/ArticleIdList/ArticleId")}
        types = [t.text for t in body.findall("PublicationTypeList/PublicationType") if t.text]
        out.append({"pmid": pmid, "title": "".join(body.find("ArticleTitle").itertext()).strip()
                    if body.find("ArticleTitle") is not None else "",
                    "authors": authors[:8], "more_authors": max(0, len(authors) - 8),
                    "journal": (body.findtext("Journal/Title") or "").strip(), "year": year,
                    "kind_of_study": kind_of_study(types), "publication_types": types,
                    "abstract": "\n".join(parts), "doi": own.get("doi", ""), "pmc": own.get("pmc", ""),
                    "url": "https://pubmed.ncbi.nlm.nih.gov/%s/" % pmid if pmid else "",
                    "free_copy": "https://pmc.ncbi.nlm.nih.gov/articles/%s/" % own["pmc"] if own.get("pmc") else "",
                    "status": "unverified"})
    return out


def find(query, limit=15, since_year=None, contact_email=None, transport=None, pause=PAUSE):
    """Search and fetch. Returns (papers, total_found). Lookups only."""
    query = str(query or "").strip()
    if len(query) < 3:
        raise store.ResearchError("Say what to look for, in a few words.")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_PAPERS:
        raise store.ResearchError("Ask for between 1 and %d papers." % MAX_PAPERS)
    email = check_email(contact_email)
    transport = transport or Transport(allow_runs=False)
    who = {"tool": TOOL}
    if email:
        who["email"] = email

    params = dict(who, db="pubmed", term=query, retmax=limit, retmode="json", sort="relevance")
    if since_year:
        params.update(mindate=str(int(since_year)), maxdate="3000", datetype="pdat")
    try:
        found = json.loads(_get(transport, EUTILS + "/esearch.fcgi", params))["esearchresult"]
        ids, total = [str(i) for i in found.get("idlist") or []][:limit], int(found.get("count") or 0)
    except (ValueError, KeyError, TypeError):
        raise store.ResearchError("The research index sent something unreadable. Try again in a few minutes.")
    if not ids:
        return [], total
    time.sleep(pause)
    papers = parse_articles(_get(transport, EUTILS + "/efetch.fcgi",
                                 dict(who, db="pubmed", id=",".join(ids), retmode="xml", rettype="abstract")))
    order = {pmid: n for n, pmid in enumerate(ids)}
    papers.sort(key=lambda p: order.get(p["pmid"], len(order)))

    if email:
        for p in papers:
            if p["free_copy"] or not p["doi"]:
                continue
            time.sleep(pause)
            try:
                data = json.loads(_get(transport, "%s/%s" % (UNPAYWALL, urllib.parse.quote(p["doi"], safe="/")),
                                       {"email": email}))
                best = (data or {}).get("best_oa_location") or {}
                p["free_copy"] = best.get("url_for_pdf") or best.get("url") or ""
            except (store.ResearchError, ValueError):
                continue                        # a missing free copy is normal, not a failure of the run
    return papers[:limit], total


def render(brand, query, papers, total, looked_for_free_copies):
    regulated = (brand.data.get("business") or {}).get("regulated", "none")
    lines = ["# Published research: %s" % query, "",
             "For **%s**. Showing %d of about %s papers the index found, most relevant first." % (
                 brand.name, len(papers), store.fmt_int(total)), ""]
    if regulated and regulated != "none":
        lines += ["> **%s works in a regulated field (%s).** A paper is not permission to make a claim. Anything "
                  "drawn from here goes through the brand's sign-off, with its disclaimer, like everything else."
                  % (brand.name, regulated), ""]
    lines += ["> **Every paper below is `unverified`.** An abstract is a summary written by the authors, not the "
              "paper. Before a finding is used: open the paper, check it says what the abstract suggests, and note "
              "who was studied and how many. Quote numbers exactly as the paper gives them, with the link. The kind "
              "of study matters: one case report is not a trial, and a trial is not a review of many trials.", "",
              store.md_table(["#", "Year", "Kind of study", "Title", "Journal", "Free copy", "Link"],
                             [[n, p["year"], p["kind_of_study"], p["title"], p["journal"],
                               "yes" if p["free_copy"] else "-", p["url"]] for n, p in enumerate(papers, 1)]), ""]
    if not looked_for_free_copies:
        lines += ["Free copies were only looked for in PubMed's own library. Give your contact email next time and "
                  "a wider search for legal free copies is made too.", ""]
    for n, p in enumerate(papers, 1):
        who = ", ".join(p["authors"]) + (" and %d more" % p["more_authors"] if p["more_authors"] else "")
        lines += ["## %d. %s" % (n, p["title"]), "",
                  "%s. *%s*, %s. **%s**. Status: `unverified`." % (who or "Authors not listed", p["journal"] or
                                                                   "journal not listed", p["year"] or "year not listed",
                                                                   p["kind_of_study"]),
                  "Link: %s%s" % (p["url"], "  |  Free copy: %s" % p["free_copy"] if p["free_copy"] else ""), "",
                  p["abstract"] or "_No abstract is published for this paper._", ""]
    lines += ["## Worksheet (Claude fills this in with you)", "",
              "1. Which papers actually bear on the question? Drop the rest.",
              "2. For each one kept: what did they study, in whom, how many, and what did they find? In the paper's "
              "own numbers, with the link.",
              "3. Where do the papers disagree?",
              "4. What can %s honestly say from this, and what can it not?" % brand.name, ""]
    return "\n".join(lines)


def search(brand, query, limit=15, since_year=None, contact_email=None, transport=None, today=None, pause=PAUSE):
    brand = store.as_brand(brand)
    papers, total = find(query, limit, since_year, contact_email, transport, pause)
    run_dir = store.new_run_dir(brand, JOB, query, today)
    store.write_json(brand, os.path.join(run_dir, "papers.json"), papers)
    store.write_text(brand, os.path.join(run_dir, "summary.md"),
                     render(brand, query, papers, total, bool(check_email(contact_email))))
    store.write_record(brand, run_dir, JOB, {"query": query, "limit": limit, "since_year": since_year,
                                             "wider_free_copy_lookup": bool(check_email(contact_email))},
                       extra={"returned": len(papers), "found_in_total": total,
                              "cost": {"estimated_usd": 0, "note": "No cost: both services are free."}})
    return {"ran": True, "folder": store.rel(brand, run_dir), "count": len(papers), "total": total, "warnings": []}
