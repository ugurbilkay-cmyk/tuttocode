"""One-shot local sensor decoder; no embedded JPEG fallback or network access."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _resource_bounds():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (180, 190))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024 ** 3, 1024 ** 3))
        # macOS RLIMIT_AS is not an effective memory bound; native sensor sizes
        # are also checked before demosaic and wall time is enforced by parent.
        if sys.platform.startswith("linux"):
            resource.setrlimit(resource.RLIMIT_AS, (3 * 1024 ** 3, 3 * 1024 ** 3))
    except (ImportError, ValueError, OSError):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--settings", required=True)
    args = parser.parse_args()
    _resource_bounds()
    from app import raw_development as R
    import numpy as np
    try:
        result = R._decode_native(args.input, json.loads(args.settings))
        np.save(args.output / "linear.npy", result.linear, allow_pickle=False)
        np.save(args.output / "preview.npy", result.preview, allow_pickle=False)
        (args.output / "report.json").write_text(json.dumps(result.report, sort_keys=True))
    except R.Unavailable:
        print("RAW dependency unavailable", file=sys.stderr)
        return 3
    except Exception:
        # Native errors may contain private local filenames. The parent provides
        # a useful generic error without exposing worker stderr in the UI.
        print("RAW sensor development failed", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
