"""The review page: one brand's posts on one local page, to approve, change or turn down.

    store.py    the rules and the file handling (no web server in it, so export can share it)
    server.py   the local web server: create_app(brand, batch_paths) and serve(...)
    static/     the page itself, one self-contained file

Nothing in this package sends anything anywhere. It reads and writes batch files on this computer.
"""
