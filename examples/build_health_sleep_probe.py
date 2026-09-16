"""Build the Health sleep-stage probe from the earlier Shortcuts experiment."""

from __future__ import annotations

import argparse
from pathlib import Path

from py2shortcuts.health import build_sleep_stage_probe
from py2shortcuts.plist import compile_xml_plist
from py2shortcuts.signing import sign_xml_plist


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("Sleep-Stage-Write-Probe.plist"),
        help="XML workflow plist output path",
    )
    parser.add_argument(
        "--sign",
        action="store_true",
        help="upload the XML plist to the explicit third-party signing service",
    )
    parser.add_argument(
        "--signed-output",
        type=Path,
        default=Path("Sleep-Stage-Write-Probe.shortcut"),
        help="signed shortcut output path when --sign is given",
    )
    args = parser.parse_args()

    xml_plist = compile_xml_plist(build_sleep_stage_probe())
    args.output.write_bytes(xml_plist)
    print(f"Wrote {args.output}")

    if args.sign:
        args.signed_output.write_bytes(sign_xml_plist(xml_plist))
        print(f"Wrote {args.signed_output}")


if __name__ == "__main__":
    main()
