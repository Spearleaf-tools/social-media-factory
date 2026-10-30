"""demo.py - one spec for every no-key format, filled with copy that is obviously a placeholder.

Used by `factory.py visuals --brand <id> --demo` so a person can see what each format looks
like in THEIR colours before writing a word, and by the tests. Every line says it is sample
text, and the numbers are zeros, so a demo picture cannot be mistaken for a real claim.
"""
from __future__ import annotations


def demo_specs(identity, size="portrait"):
    """Specs for all NO_KEY_FORMATS, in that order, for one of the brand's identities."""
    def spec(fmt, slides, **extra):
        out = {"format": fmt, "identity": identity, "size": size, "name": "demo-" + fmt, "slides": slides}
        out.update(extra)
        return out

    return [
        spec("carousel", [
            {"kind": "cover", "eyebrow": "Sample carousel", "headline": "Your strongest opening line goes here",
             "accent": ["opening line"], "kicker": "This is placeholder copy. Replace every word with your own."},
            {"kind": "point", "eyebrow": "Point one", "headline": "One idea per slide.\nSay it plainly.",
             "accent": ["One idea"], "kicker": "Sample text: a supporting sentence sits here, two lines at most."},
            {"kind": "steps", "eyebrow": "The method", "title": "A *three step* sample",
             "steps": [{"label": "Step one", "head": "*N*ame the problem",
                        "body": "Placeholder: say what goes wrong, in the reader's own words."},
                       {"label": "Step two", "head": "*S*how the fix",
                        "body": "Placeholder: the one change that makes the difference."},
                       {"label": "Step three", "head": "*P*rove it works",
                        "body": "Placeholder: what they will see when it is working."}],
             "result": "Sample result line: what they *get* at the end."},
            {"kind": "checklist", "eyebrow": "Save this", "title": "A sample list worth saving",
             "items": ["Placeholder row: keep each line short", "Placeholder row: start with a verb",
                       "Placeholder row: one thought per line", "Placeholder row: end on the useful one"]},
            {"kind": "compare",
             "left": {"tag": "Before", "title": "The old way", "note": "sample column",
                      "items": ["Placeholder: what people do now", "Placeholder: why it costs them",
                                "Placeholder: what they put up with"]},
             "right": {"tag": "After", "title": "The better way", "note": "sample column",
                       "items": ["Placeholder: what to do instead", "Placeholder: why it is easier",
                                 "Placeholder: what changes for them"]}},
            {"kind": "stat", "eyebrow": "Sample number", "stat": "00%",
             "headline": "A made-up figure, shown only for layout.", "accent": ["made-up"],
             "kicker": "Swap in a number you can point to, and say where it comes from.",
             "source": "placeholder, not a real source"},
            {"kind": "cta", "eyebrow": "Your turn", "headline": "Tell them the one next step.",
             "accent": ["one next step"], "kicker": "Placeholder copy. One action, nothing else.",
             "button": "Sample button"},
        ], pdf=True),
        spec("stat", [{"eyebrow": "Sample stat card", "stat": "00%", "headline": "of this card is placeholder copy.",
                       "accent": ["placeholder"], "kicker": "Use a real figure from your own records here.",
                       "button": "Sample button", "source": "placeholder, not a real source"}]),
        spec("split", [{"eyebrow": "Sample split card",
                        "before": {"tag": "Before", "value": "00", "sub": "sample value"},
                        "after": {"tag": "After", "value": "00", "sub": "sample value"},
                        "headline": "The contrast is the message. This one is a placeholder.",
                        "accent": ["contrast"], "button": "Sample button"}]),
        spec("alert", [{"eyebrow": "Sample alert card", "headline": "A blunt sample warning goes here.",
                        "accent": ["sample warning"],
                        "support": "Placeholder: one sentence on what it costs to ignore it.",
                        "button": "Sample button"}]),
        spec("headline", [{"eyebrow": "Sample headline card", "headline": "One large sample claim. Nothing else.",
                           "accent": ["sample claim"],
                           "support": "Placeholder: the single line that backs it up.",
                           "button": "Sample button"}]),
        spec("notes", [{"title": "Sample note: three things worth writing down",
                        "items": ["Placeholder line one", "Placeholder line two, a little longer than the first",
                                  "Placeholder line three"],
                        "closer": "Sample closing line."},
                       {"text": "A single sample thought, written like a note to yourself."}]),
        spec("post-screenshot", [{"text": "This is a sample post.\n\nIt is placeholder text, set the way a short "
                                          "post looks when someone screenshots it."},
                                 {"text": "Second sample post. Replace me."}]),
        spec("bold-text", [{"headline": "Sample headline\nin capitals", "accent": ["capitals"],
                            "subline": "Placeholder second line. Short and blunt.", "button": "Sample button"},
                           {"headline": "One sample\nidea.", "accent": ["idea."], "layout": "statement",
                            "subline": "Placeholder supporting line.", "ground": "accent"}]),
    ]
