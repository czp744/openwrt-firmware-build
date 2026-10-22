"""Fetch fixed artifacts and prepare the official ImageBuilder; no installer scripts."""
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import urllib.request

root = Path.cwd()
lock = json.loads((root / "sources.lock.json").read_text())
downloads = root / "work/downloads"
records = root / "output/records"


def fetch(url, target, expected=None):
    assert url.startswith(("https://downloads.openwrt.org/", "https://github.com/", "https://raw.githubusercontent.com/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "openwrt-imagebuilder-provenance"})
    with urllib.request.urlopen(req, timeout=120) as response, target.open("wb") as out:
        shutil.copyfileobj(response, out)
    actual = hashlib.sha256(target.read_bytes()).hexdigest()
    if expected and actual != expected:
        raise RuntimeError(f"SHA256 mismatch: {url}: {actual}")
    print(f"downloaded {target.name} sha256={actual}", flush=True)
    return actual


ow = lock["openwrt"]
fetch(ow["base_url"] + "sha256sums", records / "official-sha256sums")
expected_line = f'{ow["sha256"]} *{ow["imagebuilder"]}'
assert expected_line in (records / "official-sha256sums").read_text().splitlines()
fetch(ow["base_url"] + "profiles.json", records / "official-profiles.json", ow["profiles_sha256"])
fetch(ow["base_url"] + ow["imagebuilder"], downloads / ow["imagebuilder"], ow["sha256"])
for part in ("openclash", "mihomo"):
    item = lock[part]
    fetch(item["url"], downloads / item["filename"], item["sha256"])
for name in ("config.buildinfo", "feeds.buildinfo", "version.buildinfo"):
    line = next(x for x in (records / "official-sha256sums").read_text().splitlines() if x.endswith("*" + name))
    fetch(ow["base_url"] + name, records / name, line.split()[0])

archive = downloads / ow["imagebuilder"]
listing = subprocess.check_output(["tar", "--zstd", "-tf", str(archive)], text=True).splitlines()
for name in listing:
    path = PurePosixPath(name)
    assert not path.is_absolute() and ".." not in path.parts
top = listing[0].split("/")[0]
subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(root / "work")], check=True)
ib = root / "work/imagebuilder"
(root / "work" / top).rename(ib)
assert "CONFIG_USE_APK=y" in (ib / ".config").read_text()
shutil.copy2(downloads / lock["openclash"]["filename"], ib / "packages" / lock["openclash"]["filename"])
shutil.copy2(ib / "repositories", records / "repositories.original")
shutil.copy2(ib / ".config", records / "imagebuilder.config")

# The official package installation uses --no-scripts. Run our reviewed hook
# before official post-install handling and after final rootfs preparation.
makefile = ib / "Makefile"
text = makefile.read_text()
needle = '\t$(MAKE) -s prepare_rootfs\n'
assert text.count(needle) == 1
text = text.replace(needle,
    '\tpython3 "$$ROOT/scripts/sanitize.py" pre "$(TARGET_DIR)"\n' + needle +
    '\tpython3 "$$ROOT/scripts/sanitize.py" post "$(TARGET_DIR)"\n')
# 25.12.6 FormatPackages otherwise retains pkg_ver from the previous item when
# a version-pinned requested package is followed by an unversioned default.
# Reset that temporary variable on each iteration; retain every official default.
needle = '  $(eval pkg_name:=$(firstword $(subst =, ,$(pkg))))\n'
assert text.count(needle) == 1
text = text.replace(needle, needle + '  $(eval pkg_ver:=)\n')
makefile.write_text(text)
# Do not source the third-party init script on the build host. It is shipped
# intact in the image; the service has no boot symlink and enable remains zero.
rootfs = ib / "include/rootfs.mk"
text = rootfs.read_text()
needle = '\t\tfor script in ./etc/init.d/*; do \\\n'
assert text.count(needle) == 1
text = text.replace(needle, needle + '\t\t\t[ "$$script" = "./etc/init.d/openclash" ] && continue; \\\n')
rootfs.write_text(text)
shutil.copy2(makefile, records / "imagebuilder.Makefile.used")
shutil.copy2(rootfs, records / "rootfs.mk.used")

overlay = root / "work/overlay"
core = overlay / "etc/openclash/core/clash_meta"
core.parent.mkdir(parents=True)
with gzip.open(downloads / lock["mihomo"]["filename"], "rb") as src, core.open("wb") as dst:
    shutil.copyfileobj(src, dst)
core.chmod(0o755)
assert core.read_bytes()[:5] == b"\x7fELF\x02"
(records / "mihomo-binary.sha256").write_text(hashlib.sha256(core.read_bytes()).hexdigest() + "  /etc/openclash/core/clash_meta\n")
# Retain upstream defaults and generic resources. The installed config is
# checked for enable=0 and absence of subscriptions and secrets before imaging.
for item in ("sources.lock.json", "packages.txt"):
    shutil.copy2(root / item, records / item)

