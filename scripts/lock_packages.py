"""Freeze the successful APK resolver's complete versioned result for this run."""
import json
from pathlib import Path
import re

records = Path("output/records")
packages = {}
for line in (records / "resolver.log").read_text().splitlines():
    match = re.fullmatch(r"([a-zA-Z0-9_+.-]+) - (\S+)", line)
    if match:
        packages[match[1]] = match[2]
requested = [x.split("#", 1)[0].strip() for x in Path("packages.txt").read_text().splitlines()]
requested = [x for x in requested if x and not x.startswith("-")]
missing = set(requested) - packages.keys()
assert not missing, f"Requested packages unresolved: {sorted(missing)}"
assert packages["luci-app-openclash"].startswith("0.48.002")
assert packages["kernel"].startswith("6.12.112")
for required in ("firewall4", "odhcp6c", "odhcpd-ipv6only", "dropbear", "netifd", "kmod-igc"):
    assert required in packages
(records / "packages.lock.args").write_text(" ".join(f"{k}={v}" for k, v in sorted(packages.items())) + "\n")
(records / "resolved-packages.json").write_text(json.dumps(packages, indent=2) + "\n")
print(f"Resolved and pinned {len(packages)} packages")

