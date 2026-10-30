"""Short-form video scripts: pitch, approve, write, check, teleprompter, index, audit.

Everything here belongs to ONE named brand and lives inside that brand's folder:

    Client/<brand>/Studio/scripts/<batch>/
        manifest.json                     the batch's record: every script and where it has got to
        pitches.md                        the pitch sheet a person reads and says yes or no to
        <id>-<slug>.md                    one script: what is said, what is shown, where facts come from
        <id>-<slug>.teleprompter.txt      the same script as plain words to read on camera
        INDEX.md                          the page a person films from
        audit.md                          what the published numbers say, and the one thing to test next

A script moves through five steps, in order:

    pitched -> approved -> draft -> validated -> recorded

Only a person's yes moves a pitch to approved. Only a clean check moves a draft to validated.
Nothing in this package talks to a network, and nothing in it writes a fact: it checks that the
facts a script states can be traced to the brand's own material.
"""
from __future__ import annotations

from smf.studio.files import StudioError


class ScriptsError(StudioError):
    """A problem with a script or a batch of scripts, worded for the person, not the programmer."""
