"""cli.py - verbs that run inside (or, for status/doctor, possibly outside) the Social Media Factory's Python."""
from __future__ import annotations

VERBS = {
    "status": ("smf.status", "main", "what is ready and what to do next"),
    "doctor": ("smf.doctor", "main", "prove the installed pieces work"),
    "guide": ("smf.guide", "main", "write GUIDE.md from the feature table (--check to verify it is current)"),
    "new-brand": ("smf.brands", "cli_new", "create a complete, empty brand"),
    "update-brand": ("smf.brands", "cli_update", "merge changed answers into a brand's settings"),
    "check-brand": ("smf.brands", "cli_check", "is a brand's settings file complete and sane"),
    "onboard-page": ("smf.onboarding_page.cli", "cli_onboard_page", "onboarding on its own page on this computer; --wait, --status, --result, --stop for the hand-off"),
    "checklist": ("smf.checklist", "main", "the accounts and keys this brand needs, and which are done"),
    "sync-brand": ("smf.brands", "cli_sync", "derive the tools' settings from brand-master.json"),
    "plan": ("smf.studio.writing_cli", "cli_plan", "plan a batch: jobs, hooks, shapes, visuals and calls to action"),
    "topics": ("smf.studio.writing_cli", "cli_topics", "planning inputs and the topic bank: inputs, list, add, approve, cut, revise, check"),
    "contract": ("smf.studio.writing_cli", "cli_contract", "the brief Claude writes one post from"),
    "validate-draft": ("smf.studio.writing_cli", "cli_validate", "check a draft: rules, facts, repeats, takeaway"),
    "facts": ("smf.studio.writing_cli", "cli_facts", "the brand's verified facts: list, add"),
    "journal": ("smf.studio.writing_cli", "cli_journal", "the owner's thinking journal, word for word: add, list, private, public"),
    "posts": ("smf.studio.batch_cli", "main", "put checked drafts into a batch: add, attach, check, schedule, list"),
    "scripts": ("smf.scripts.scripts_cli", "cli_scripts", "short-form video scripts: pitch, approve, check, teleprompter, index, audit"),
    "research": ("smf.research.research_cli", "cli_research", "find out what is working and what people are asking for"),
    "youtube": ("smf.youtube.youtube_cli", "cli_youtube", "long-form YouTube: titles, thumbnail, structure, description, deck, teleprompter, question slate"),
    "review": ("smf.studio.review_cli", "cli_review", "open the review page for one brand's posts"),
    "export": ("smf.studio.review_cli", "cli_export", "write approved posts to a ready-to-post folder"),
    "visuals": ("smf.studio.render_cli", "cli_visuals", "draw a post's pictures from a spec, or --demo for one of every format"),
    "recordings": ("smf.video.video_cli", "cli_recordings", "list a brand's recordings and whether each has a transcript"),
    "transcribe": ("smf.video.video_cli", "cli_transcribe", "recording to transcript with who said what (shows the cost first; sends only with --confirm)"),
    "find-clips": ("smf.video.video_cli", "cli_find_clips", "flag compliance and lay the transcript out for choosing clips"),
    "check-cut-list": ("smf.video.video_cli", "cli_check_cut_list", "prove every hook and boundary in a cut list is really in the transcript"),
    "rough-cut": ("smf.video.video_cli", "cli_rough_cut", "cut list to stitched rough cuts, snapped to the words"),
    "fine-cut": ("smf.video.video_cli", "cli_fine_cut", "remove fillers and dead air, smoothly"),
    "validate-cuts": ("smf.video.video_cli", "cli_validate_cuts", "transcribe every cut back and check heads, joins and tails"),
    "variants": ("smf.video.variants_cli", "cli_variants", "several different-looking versions of each clip, with text, captions and any disclaimer: plan, render, verify, deliver, status"),
    "describe": ("smf.video.variants_cli", "cli_describe", "the words under each video: contract, check"),
    "sync": ("smf.video.multicam_cli", "cli_sync", "line recordings up by their sound: how far apart, and which way"),
    "multicam": ("smf.video.multicam_cli", "cli_multicam", "two cameras into one video that shows whoever is talking: plan, render, clips, verify"),
    "montage": ("smf.video.montage_cli", "cli_montage", "a narrated film cut from many sources: footage, draft, new, check, voice, words, titles, render"),
    "accounts": ("smf.posting.posting_cli", "cli_accounts", "list the scheduling service's brands and connected networks, and link them"),
    "schedule": ("smf.posting.posting_cli", "cli_schedule", "schedule approved posts (a preview that sends nothing, unless --confirm)"),
    "shorts": ("smf.posting.posting_cli", "cli_shorts", "one short a day from a folder of finished videos"),
    "promote": ("smf.posting.posting_cli", "cli_promote", "advanced, off by default: test every version on TikTok, promote the winner"),
    "results": ("smf.posting.posting_cli", "cli_results", "did it go out, and how did it do"),
    "proof": ("smf.studio.proof", "main", "add to or list the brand's proof library"),
}


def main(argv):
    from smf import bootstrap
    bootstrap.utf8_output()          # a post or a brand name can be in any language; so can a folder
    verb = argv[0] if argv else "help"
    if verb not in VERBS:
        print("Unknown command: %s\n" % verb)
        print("Commands:")
        print("  %-12s %s" % ("setup", "install what this computer needs"))
        for name, (_m, _f, about) in VERBS.items():
            print("  %-12s %s" % (name, about))
        return 2
    module, func, _about = VERBS[verb]
    mod = __import__(module, fromlist=[func])
    return getattr(mod, func)(argv[1:])
