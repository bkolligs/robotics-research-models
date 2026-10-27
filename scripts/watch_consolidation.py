"""Display progress and ETA from an existing run without restarting it.

uv run --no-sync python scripts/watch_consolidation.py [--once]
"""
import argparse
import json
import time
from pathlib import Path
from mentions.progress import format_progress


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log', type=Path, default=Path('data/modal-consolidation.log'))
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    offset, latest, previous = 0, None, None
    while True:
        with args.log.open() as handle:
            handle.seek(offset)
            for line in handle:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict) and event.get('event') == 'consolidation_progress':
                    latest = event
            offset = handle.tell()
        if latest is not None and latest != previous:
            print(format_progress(latest), flush=True)
            previous = latest
        if args.once or (latest and latest['stage'] in ('complete', 'failed')):
            return
        time.sleep(2)


if __name__ == '__main__':
    main()
