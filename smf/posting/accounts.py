"""accounts.py - see what the scheduling service has, and link a brand to it by ID, never by name.

Onboarding needs two things from here, and both are read-only against the service:

    open_provider(brand)                     the brand's own provider, unable to write by default
    list_accounts(provider)                  what the key can see: each account's id, label, networks

and one that builds settings without touching the service at all:

    build_targets(brand, accounts, provider_brand_id, {"person": ["instagram", "tiktok"]})

WHY BY ID ONLY
An agency key sees many accounts, and their labels look alike: two bakeries, a clinic and its
sister clinic. Matching a brand to "the one that sounds right" is how one company's words end up
on another company's page. So nothing here ever compares names. A person picks one account from
the list, its ID goes into the brand's settings, and every later send looks that ID up in THIS
brand's settings and nowhere else. The identity -> platform mapping is explicit for the same
reason: nothing is inferred from what happens to be connected.

AND WHY THE ID IS NOT ENOUGH ON ITS OWN
An account on the scheduling service is a folder, not a page: someone can disconnect its Facebook
and connect a different Facebook page to the same account, and its id never changes. So each
entry also writes down WHERE the service says that network points right now (`destination`: the
page, channel or handle, exactly as the service reports it). Sending compares the two, and a
difference stops that network rather than posting a brand's words on a stranger's page. A link
saved before the Factory kept this note has no `destination`: that is not an error, it just has
to be confirmed once by running this step again.
"""
from __future__ import annotations

from smf import brands
from smf.brands import BrandError
from smf.posting.provider import ProviderError, Transport
from smf.posting.send import other_brand_claims
from smf.studio.lint import PLATFORM_CHAR_LIMITS

PLATFORMS = tuple(sorted(PLATFORM_CHAR_LIMITS))


class AccountsError(Exception):
    """Worded for the person."""


def provider_name(brand):
    return (brand.data.get("accounts") or {}).get("provider") or "none"


def open_provider(brand, allow_writes=False, opener=None):
    """The provider THIS brand is set up to use. There is no default provider: a brand that has
    not chosen one gets a plain error. `allow_writes` stays False unless a person confirmed."""
    name = provider_name(brand)
    if name == "none":
        raise AccountsError("%s has not chosen a scheduling service yet. Choose one in onboarding, or save a "
                            "ready-to-post folder instead." % brand.name)
    if name == "metricool":
        from smf.posting.metricool import Metricool
        return Metricool(Transport(allow_writes=bool(allow_writes), opener=opener))
    raise AccountsError("%s is set up to use '%s', which this copy of the Factory cannot talk to."
                        % (brand.name, name))


def list_accounts(provider):
    """[{provider_brand_id, label, networks, destinations}] exactly as the service reports them.
    `destinations` is {network: where it points}, as far as the service says. A read."""
    out = []
    for a in provider.list_accounts():
        where = a.get("destinations") or {}
        out.append({"provider_brand_id": a.get("provider_brand_id"), "label": a.get("label") or "",
                    "networks": sorted(a.get("networks") or []),
                    "destinations": {k: str(v) for k, v in where.items() if str(v or "")}})
    return out


def overview(brand, accounts):
    """The account list with two facts added per account: which of THIS brand's identities
    already point at it, and whether another brand on this computer claims it."""
    mine = {}
    for t in brand.targets():
        if t.get("provider_brand_id") is not None:
            mine.setdefault(str(t["provider_brand_id"]), []).append("%s/%s" % (t["identity"], t["platform"]))
    claims = other_brand_claims(brand, provider_name(brand))
    out = []
    for a in accounts:
        pbid = str(a["provider_brand_id"])
        others = sorted({b for (_platform, claimed), ids in claims.items() if claimed == pbid for b in ids})
        out.append(dict(a, linked_here=sorted(mine.get(pbid, [])), claimed_by_other_brands=others))
    return out


def build_targets(brand, accounts, provider_brand_id, mapping):
    """The `accounts.targets` entries for ONE chosen account and an explicit mapping
    {identity: [platform, ...]}. Raises AccountsError instead of guessing.

    `connected` is taken from what the service reports for that account right now, so a platform
    that is mapped but not connected is written down as not connected, and will block a send.
    `destination` is where the service says that network points right now; a send compares it
    again and stops if it has moved. See the top of this file."""
    if isinstance(provider_brand_id, bool) or not str(provider_brand_id).strip().lstrip("-").isdigit():
        raise AccountsError("Pick the account by its id number from the list. A name is never enough, because "
                            "names can look alike.")
    wanted = str(int(str(provider_brand_id).strip()))
    chosen = [a for a in accounts if str(a.get("provider_brand_id")) == wanted]
    if len(chosen) != 1:
        raise AccountsError("The key in use cannot see an account with the id %s. Accounts it can see: %s"
                            % (wanted, ", ".join("%s (%s)" % (a["provider_brand_id"], a["label"])
                                                 for a in accounts) or "none"))
    account = chosen[0]
    if not isinstance(mapping, dict) or not mapping:
        raise AccountsError("Say which identity posts on which platforms, for example person: instagram, tiktok.")
    claims = other_brand_claims(brand, provider_name(brand))
    entries, seen = [], {}
    for identity, platforms in mapping.items():
        try:
            brand.identity(identity)
        except BrandError as e:
            raise AccountsError(str(e))
        if isinstance(platforms, str):
            platforms = [platforms]
        for platform in platforms:
            platform = str(platform).strip().lower()
            if platform not in PLATFORMS:
                raise AccountsError("'%s' is not a platform the Factory knows. It knows: %s"
                                    % (platform, ", ".join(PLATFORMS)))
            if platform in seen and seen[platform] != identity:
                raise AccountsError("One account has one %s. It cannot be both '%s' and '%s'. Each identity needs "
                                    "its own account on the service." % (platform, seen[platform], identity))
            others = sorted(set(claims.get((platform, wanted), [])))
            if others:
                raise AccountsError("That %s account is already linked to another brand on this computer (%s). "
                                    "One account belongs to one brand." % (platform, ", ".join(others)))
            for t in brand.targets():
                if (t["platform"] == platform and str(t.get("provider_brand_id")) == wanted
                        and t["identity"] != identity):
                    raise AccountsError("This brand already uses that %s account for '%s'."
                                        % (platform, t["identity"]))
            seen[platform] = identity
            entry = {"identity": identity, "platform": platform, "provider_brand_id": int(wanted),
                     "connected": platform in account["networks"]}
            where = str((account.get("destinations") or {}).get(platform) or "")
            if where:
                entry["destination"] = where
            entries.append(entry)
    return entries


def merged_targets(brand, entries):
    """The brand's full target list with `entries` put in: an entry replaces the brand's existing
    one for the same (identity, platform); everything else is kept as it was."""
    fresh = {(e["identity"], e["platform"]) for e in entries}
    kept = [dict(t) for t in brand.targets() if (t["identity"], t["platform"]) not in fresh]
    return kept + [dict(e) for e in entries]


def link(brand, entries):
    """Save the entries into the brand's settings. Validated before anything is written, so a
    change that would break the brand is refused and nothing on disk changes."""
    updated = brands.update(brand.id, {"accounts": {"targets": merged_targets(brand, entries)}})
    brands.sync(updated)
    return updated


def connection_changes(brand, accounts):
    """Where the brand's settings and the service disagree about what is connected right now.
    [{identity, platform, settings_say, service_says}] ; an empty list means they agree."""
    by_id = {str(a["provider_brand_id"]): set(a["networks"]) for a in accounts}
    out = []
    for t in brand.targets():
        pbid = t.get("provider_brand_id")
        if pbid is None:
            continue
        networks = by_id.get(str(pbid))
        now = bool(networks is not None and t["platform"] in networks)
        if bool(t.get("connected")) != now:
            out.append({"identity": t["identity"], "platform": t["platform"], "settings_say": bool(t.get("connected")),
                        "service_says": now, "account_visible": networks is not None})
    return out


def destination_changes(brand, accounts):
    """Connected networks whose page or profile is not the one this brand linked. Each is a
    sentence for the person plus the two values. A send stops on exactly these, so this is what
    "run the accounts step again to confirm it" is for.
    [{identity, platform, kind: "moved" | "never-confirmed", was, now, note}]."""
    by_id = {str(a["provider_brand_id"]): a for a in accounts}
    out = []
    for t in brand.targets():
        account = by_id.get(str(t.get("provider_brand_id")))
        if not account or t["platform"] not in set(account["networks"]):
            continue                                        # not connected: connection_changes says so
        where = str((account.get("destinations") or {}).get(t["platform"]) or "")
        linked_to = str(t.get("destination") or "")
        if not where or where == linked_to:
            continue
        kind = "moved" if linked_to else "never-confirmed"
        out.append({"identity": t["identity"], "platform": t["platform"], "kind": kind, "was": linked_to,
                    "now": where,
                    "note": ("the %s account for '%s' now points at %s on the scheduling service, not at %s. "
                             "Nothing will be sent there until this is saved again." % (t["platform"], t["identity"],
                                                                                        where, linked_to))
                    if linked_to else
                    ("the %s account for '%s' was linked before the Factory kept a note of which page or profile "
                     "it points at. Save it again to confirm it is %s." % (t["platform"], t["identity"], where))})
    return out


__all__ = ["AccountsError", "ProviderError", "open_provider", "list_accounts", "overview", "build_targets",
           "merged_targets", "link", "connection_changes", "destination_changes", "provider_name", "PLATFORMS"]
