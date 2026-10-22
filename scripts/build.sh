#!/usr/bin/env bash
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true ]] || { echo 'This build is restricted to GitHub Actions.'; exit 1; }
[[ "${RUNNER_ENVIRONMENT:-}" == github-hosted ]] || { echo 'A GitHub-hosted runner is required.'; exit 1; }
ROOT="$(pwd)"
export ROOT
mkdir -p output/records output/firmware work/downloads
exec > >(tee -a output/records/build.log) 2>&1
python3 scripts/prepare.py
IB="$ROOT/work/imagebuilder"
APK="$IB/staging_dir/host/bin/apk"
"$APK" --version
"$APK" --allow-untrusted adbdump "$IB/packages/luci-app-openclash-0.48.002.apk" > output/records/openclash-adbdump.txt
file work/overlay/etc/openclash/core/clash_meta | tee output/records/mihomo-file.txt
readelf -h work/overlay/etc/openclash/core/clash_meta > output/records/mihomo-elf.txt
readelf -l work/overlay/etc/openclash/core/clash_meta >> output/records/mihomo-elf.txt
if grep -q INTERP output/records/mihomo-elf.txt; then
  echo 'Unexpected dynamically linked Mihomo binary'; exit 1
fi
# This only reports the version; no config, network service or proxy is started.
timeout 10 work/overlay/etc/openclash/core/clash_meta -v | tee output/records/mihomo-version.txt
grep -F '1.19.33' output/records/mihomo-version.txt
PKGS="$(sed -e 's/#.*//' -e '/^[[:space:]]*$/d' packages.txt | tr '\n' ' ')"
make -C "$IB" info | tee output/records/imagebuilder-info.txt
# Resolving/installing packages uses official ImageBuilder --no-scripts behavior.
make -C "$IB" manifest PROFILE=generic PACKAGES="$PKGS" STRIP_ABI=1 | tee output/records/resolver.log
python3 scripts/lock_packages.py
LOCKED="$(cat output/records/packages.lock.args)"
# No first-boot proxy configuration, subscription, policies or identity is supplied.
make -C "$IB" image PROFILE=generic PACKAGES="$LOCKED -dnsmasq -ip-tiny" \
  FILES="$ROOT/work/overlay" ROOTFS_PARTSIZE=1024 \
  DISABLED_SERVICES="openclash pbr zerotier" \
  BIN_DIR="$ROOT/work/images" | tee output/records/imagebuilder.log
python3 scripts/verify.py
cp sources.lock.json packages.txt README.md output/firmware/
cp output/records/installed-packages.txt output/records/verification.json output/firmware/
cp output/records/mihomo-version.txt output/firmware/
(cd output/firmware && sha256sum *.img.gz > SHA256SUMS)
(cd output/firmware && sha256sum -c SHA256SUMS)
echo 'UEFI images verified structurally. No VM or hardware boot test was performed.'
