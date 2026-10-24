"""Entry point of the workflow step: python3 -m reviewer."""

import json
import os
import sys

from . import job, transport


def main():
    try:
        with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as event_file:
            event = json.load(event_file)
        return job.run(
            os.environ.get("GITHUB_EVENT_NAME", ""),
            event,
            http=transport.send,
            github_token=os.environ["GITHUB_TOKEN"],
            anthropic_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            log=_log,
            github_api=os.environ.get("GITHUB_API_URL", job.GITHUB_API),
        )
    except Exception as error:
        # An exception's message may quote the event or a response; only its
        # type reaches the log.
        _log(f"error: {type(error).__name__}")
        return 1


def _log(line):
    print(line, flush=True)


if __name__ == "__main__":
    sys.exit(main())
