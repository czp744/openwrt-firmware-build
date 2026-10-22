"""Restrict changes to the temporary firmware root; no host network operations."""
import gzip
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tarfile

project = Path(os.environ["ROOT"]).resolve()
stage, argument = sys.argv[1:]
root = Path(argument).resolve()
assert root.is_relative_to(project / "work/imagebuilder/build_dir")
assert (root / "etc/openwrt_release").is_file()
records = project / "output/records"

if stage == "pre":
    # APK install skipped scripts. Preserve the actual maintainer scripts for
    # inspection, then make OpenClash's build-time post-install a no-op.
    # Official packages retain their original maintainer scripts.
    scripts = root / "lib/apk/db/scripts.tar"
    compressed = scripts.read_bytes().startswith(b"\x1f\x8b")
    buf = io.BytesIO()
    seen = []
    with tarfile.open(scripts, "r:*") as src, tarfile.open(fileobj=buf, mode="w") as dst:
        for member in src:
            payload = src.extractfile(member).read() if member.isfile() else None
            if "luci-app-openclash" in member.name and payload is not None:
                seen.append(member.name)
                (records / (Path(member.name).name + ".review.txt")).write_bytes(payload)
                if member.name.endswith(".post-install"):
                    payload = b"#!/bin/sh\nexit 0\n"
                    member.size = len(payload)
            dst.addfile(member, io.BytesIO(payload) if payload is not None else None)
    assert seen, "OpenClash APK maintainer script inventory missing"
    payload = buf.getvalue()
    scripts.write_bytes(gzip.compress(payload, mtime=0) if compressed else payload)
    print("Recorded OpenClash maintainer scripts; suppressed build-time execution", seen)
elif stage == "post":
    removed = []
    # Keep upstream generic resources intact. No policy or subscription is added.
    config = root / "etc/config/openclash"
    text = config.read_text()
    assert re.search(r"option\s+enable\s+['\"]?0['\"]?", text)
    assert not re.search(r"^config\s+(?:config_subscribe|servers|proxy-provider|authentication)\b", text, re.M)
    # Remove sample PBR policies and includes; keep its general defaults disabled.
    pbr = root / "etc/config/pbr"
    if pbr.exists():
        sections = re.split(r"(?=^config\s)", pbr.read_text(), flags=re.M)
        general = [s for s in sections if not re.match(r"config\s+(?:policy|include|dns_policy)\b", s)]
        text = "".join(general)
        text = re.sub(r"(option\s+enabled\s+)['\"]?1['\"]?", r"\g<1>'0'", text)
        pbr.write_text(text)
    for path in (root / "etc/rc.d").glob("*"):
        if re.fullmatch(r"[SK]\d+(?:openclash|pbr|zerotier)", path.name):
            path.unlink()
    (records / "sanitized-content.json").write_text(json.dumps(removed, indent=2) + "\n")
    (records / "rootfs-path.txt").write_text(str(root) + "\n")
    print("Preserved upstream resources; OpenClash, PBR and ZeroTier disabled")
else:
    raise ValueError(stage)
