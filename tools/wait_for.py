"""Wait until a file exists and has stopped changing.

usage: python tools/wait_for.py <file> <timeout_seconds> [--settle 2] [--interval 1] [--print]

For a builder waiting on notes/<area>/note-NN.md, or a manager waiting on pass-NN.md. The file counts as ready when
it exists and its size and modification time have not changed for --settle seconds (writers should still write
to a temporary name and rename it). Prints one JSON line with the result; --print also prints the file's text.
Exit 0 when ready, 1 on timeout, 2 on bad input (a negative timeout, or the path is a folder).
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ArgParser, BadInput, EXIT_GATE, EXIT_OK, run  # noqa: E402

USAGE = 'python tools/wait_for.py <file> <timeout_seconds> [--settle 2] [--interval 1] [--print]'


def stamp(p):
    try:
        st = os.stat(p)
    except OSError:
        return None
    return st.st_size, st.st_mtime_ns


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('path')
    ap.add_argument('timeout', type=float)
    ap.add_argument('--settle', type=float, default=2.0)
    ap.add_argument('--interval', type=float, default=1.0)
    ap.add_argument('--print', action='store_true', dest='show')
    a = ap.parse(argv)
    if a.timeout < 0 or a.settle < 0 or a.interval <= 0:
        raise BadInput('timeout and settle must be >= 0 and interval > 0')
    if os.path.isdir(a.path):
        raise BadInput('%s is a folder, not a file' % a.path)
    t0 = time.monotonic()
    last, since = None, None
    while True:
        now = time.monotonic()
        s = stamp(a.path)
        if s is not None:
            if s != last:
                last, since = s, now
            if now - since >= a.settle:
                print(json.dumps(dict(path=os.path.abspath(a.path), status='ready', waited_s=round(now - t0, 2),
                                      size=s[0])))
                if a.show:
                    sys.stdout.reconfigure(encoding='utf-8')
                    with open(a.path, 'r', encoding='utf-8', errors='replace') as f:
                        print(f.read())
                return EXIT_OK
        else:
            last = since = None
        if now - t0 >= a.timeout:
            print(json.dumps(dict(path=os.path.abspath(a.path), status='exists, still changing' if s else 'absent',
                                  waited_s=round(now - t0, 2))))
            return EXIT_GATE
        time.sleep(min(a.interval, max(0.05, a.timeout - (now - t0)) if a.timeout else a.interval))


if __name__ == '__main__':
    run(main)
