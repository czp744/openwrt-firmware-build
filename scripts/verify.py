"""Inspect generated disk images without mounting, booting or changing networks."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import uuid
import zlib

project = Path.cwd()
records = project / "output/records"
ib = project / "work/imagebuilder"
root = Path((records / "rootfs-path.txt").read_text().strip())
assert root.is_relative_to(ib / "build_dir")
out = project / "output/firmware"
checks = project / "work/checks"
checks.mkdir()


def digest(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def run(args):
    return subprocess.check_output([str(a) for a in args], stderr=subprocess.STDOUT)


query = run([ib / "staging_dir/host/bin/apk", "--root", root, "--no-network",
             "query", "--format", "json", "--fields", "name,version,tags", "--installed", "*"])
(records / "installed-packages.json").write_bytes(query)
data = json.loads(query)
installed = {}


def collect(value):
    if isinstance(value, list):
        for item in value:
            collect(item)
    elif isinstance(value, dict):
        if isinstance(value.get("name"), str) and isinstance(value.get("version"), str):
            installed[value["name"]] = value["version"]
        else:
            for item in value.values():
                collect(item)


collect(data)
assert installed, "Cannot read installed APK package inventory"
requested = []
for line in (project / "packages.txt").read_text().splitlines():
    name = line.split("#", 1)[0].strip()
    if name and not name.startswith("-"):
        requested.append(name)
assert set(requested) <= installed.keys(), f"Missing packages: {set(requested) - installed.keys()}"
assert installed["luci-app-openclash"].startswith("0.48.002")
for name in ("firewall4", "odhcp6c", "odhcpd-ipv6only", "dropbear", "netifd", "kmod-igc"):
    assert name in installed
assert not {"dnsmasq", "ip-tiny"} & installed.keys()
(records / "installed-packages.txt").write_text("".join(f"{k} - {v}\n" for k, v in sorted(installed.items())))

core = root / "etc/openclash/core/clash_meta"
core_sha = digest(project / "work/overlay/etc/openclash/core/clash_meta")
assert digest(core) == core_sha and os.access(core, os.X_OK)
assert (root / "etc/init.d/openclash").is_file()
assert (root / "usr/lib/lua/luci/openclash.lua").is_file()
drivers = list((root / "lib/modules").glob("**/igc.ko*"))
assert drivers, "I226-V igc module missing"
conf = (root / "etc/config/openclash").read_text()
assert re.search(r"option\s+enable\s+['\"]?0['\"]?", conf)
for field in ("dashboard_password", "password", "secret", "token"):
    assert not re.search(rf"^\s*option\s+{field}\s+['\"]?[^\s'\"]", conf, re.M), f"Preseeded {field}"
assert not re.search(r"^config\s+(?:config_subscribe|servers|proxy-provider|authentication)\b", conf, re.M)
for service in ("openclash", "pbr", "zerotier"):
    assert not list((root / "etc/rc.d").glob("S*" + service)), f"{service} starts at boot"
for path in ("etc/zerotier/identity.secret", "etc/zerotier/identity.public", "var/lib/zerotier-one/identity.secret"):
    assert not (root / path).exists(), path
assert not list((root / "etc/dropbear").glob("*host_key*"))
assert not list((root / "etc").glob("uhttpd.key"))
db = root / "lib/apk/db/installed"
assert db.is_file()
sample_paths = ["etc/config/openclash", "etc/config/firewall", "etc/config/dhcp",
                "etc/init.d/openclash", "etc/openclash/core/clash_meta", "lib/apk/db/installed",
                str(drivers[0].relative_to(root))]
expected = {path: digest(root / path) for path in sample_paths}


def decompress(source, target):
    # OpenWrt may append fwtool metadata after gzip; validate gzip's own CRC
    # while recording rather than interpreting the non-gzip image trailer.
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    trailer = b""
    with source.open("rb") as src, target.open("wb") as dst:
        while block := src.read(1024 * 1024):
            dst.write(decoder.decompress(block))
            if decoder.eof:
                trailer = decoder.unused_data + src.read()
                break
        assert decoder.eof, "Truncated gzip image"
    return len(trailer)


def inspect(source):
    folder = checks / source.name
    folder.mkdir()
    image = folder / "disk.img"
    trailer = decompress(source, image)
    with image.open("rb") as disk:
        assert disk.read(512)[510:] == b"\x55\xaa"
        header = bytearray(disk.read(512))
        assert header[:8] == b"EFI PART", "UEFI disk has no GPT header"
        size = struct.unpack_from("<I", header, 12)[0]
        crc = struct.unpack_from("<I", header, 16)[0]
        struct.pack_into("<I", header, 16, 0)
        assert zlib.crc32(header[:size]) == crc, "GPT header CRC mismatch"
        lba, count, entry_size, entries_crc = struct.unpack_from("<QIII", header, 72)
        disk.seek(lba * 512)
        table = disk.read(count * entry_size)
        assert zlib.crc32(table) == entries_crc, "GPT partition table CRC mismatch"
        partitions = []
        for i in range(count):
            entry = table[i * entry_size:(i + 1) * entry_size]
            if entry[:16] == bytes(16):
                continue
            start, end = struct.unpack_from("<QQ", entry, 32)
            partitions.append({"number": i + 1, "type": str(uuid.UUID(bytes_le=entry[:16])), "start": start, "end": end})
        boot = next(p for p in partitions if p["number"] == 1)
        rootpart = next(p for p in partitions if p["number"] == 2)
        # OpenWrt's gen_image_generic.sh defaults to MBR type 0x83, which
        # ptgen maps to Linux filesystem GUID even for the FAT EFI boot volume.
        # Validate the actual FAT volume and x86-64 EFI executable below.
        assert boot["type"] in {
            "c12a7328-f81f-11d2-ba4b-00a0c93ec93b",
            "0fc63daf-8483-4772-8e79-3d69d8477de4",
        }, f"Unexpected boot partition type: {boot['type']}"
        disk.seek(rootpart["start"] * 512)
        rootimage = folder / "rootfs.img"
        remaining = (rootpart["end"] - rootpart["start"] + 1) * 512
        with rootimage.open("wb") as dest:
            while remaining:
                block = disk.read(min(remaining, 1024 * 1024))
                assert block
                dest.write(block)
                remaining -= len(block)
    efi = folder / "bootx64.efi"
    run(["mcopy", "-i", f"{image}@@{boot['start'] * 512}", "::/efi/boot/bootx64.efi", efi])
    pe = efi.read_bytes()
    assert pe[:2] == b"MZ"
    offset = struct.unpack_from("<I", pe, 0x3c)[0]
    assert pe[offset:offset + 4] == b"PE\0\0" and struct.unpack_from("<H", pe, offset + 4)[0] == 0x8664
    with rootimage.open("rb") as file:
        magic = file.read(4)
        file.seek(1080)
        ext4 = file.read(2)
    if "squashfs" in source.name:
        assert magic == b"hsqs"
        extracted = folder / "root"
        run(["unsquashfs", "-no-progress", "-d", extracted, rootimage])
        actual = {path: digest(extracted / path) for path in sample_paths}
    else:
        assert ext4 == b"\x53\xef"
        actual = {}
        for i, path in enumerate(sample_paths):
            copy = folder / f"sample-{i}"
            run(["debugfs", "-R", f"dump /{path} {copy}", rootimage])
            assert copy.is_file(), f"File missing in ext4: {path}"
            actual[path] = digest(copy)
    assert actual == expected, "Final disk content differs from inspected rootfs"
    shutil.copy2(source, out / source.name)
    return {"file": source.name, "sha256": digest(source), "bytes": source.stat().st_size,
            "partitions": partitions, "gzip_trailing_metadata_bytes": trailer,
            "bootloader": "PE32+ x86-64 EFI application", "verified_file_sha256": actual}


images = sorted((project / "work/images").glob("*combined-efi.img.gz"))
assert len(images) == 2, f"Expected ext4 and squashfs EFI images: {images}"
report = {"status": "structural-validation-passed", "hardware_boot_test": False,
          "virtual_machine_boot_test": False, "installed_apk_count": len(installed),
          "mihomo_version": "1.19.33", "mihomo_binary_sha256": core_sha,
          "disabled_services": ["openclash", "pbr", "zerotier"],
          "images": [inspect(path) for path in images]}
(records / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
hashes = []
for folder in (ib / "dl", ib / "packages"):
    for path in sorted(folder.rglob("*.apk")):
        hashes.append(f"{digest(path)}  {path.relative_to(ib)}\n")
(records / "downloaded-apks.sha256").write_text("".join(hashes))
print(json.dumps(report, indent=2))
