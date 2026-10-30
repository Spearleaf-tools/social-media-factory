"""smf.video - turn a recording into clips: transcript, cut list, rough cut, fine cut, checked clips.

Three rules run through every file here:

  * Every hook is a line somebody really said. The tools find, check and cut; they never write copy.
  * The tools flag compliance problems. A person decides what ships.
  * A voice that is off camera (a host, a coach, a producer) never ends up inside a clip.
"""
