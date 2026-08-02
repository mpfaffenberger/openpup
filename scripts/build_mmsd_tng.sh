#!/usr/bin/env bash
set -euo pipefail

MMSD_REPOSITORY="${MMSD_REPOSITORY:-https://gitlab.com/kop316/mmsd.git}"
MMSD_REF="${MMSD_REF:-341117141f8d30949fb1294cc71ee44af9b4c90f}"
BUILD_ROOT="${BUILD_ROOT:-$HOME/.cache/openpup/mmsd-build}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/libexec/openpup}"
SOURCE_DIR="$BUILD_ROOT/source"
OUTPUT_DIR="$BUILD_ROOT/output"

mkdir -p "$BUILD_ROOT" "$INSTALL_DIR"
rm -rf "$SOURCE_DIR" "$OUTPUT_DIR"
git clone "$MMSD_REPOSITORY" "$SOURCE_DIR"
git -C "$SOURCE_DIR" checkout --detach "$MMSD_REF"
mkdir -p "$OUTPUT_DIR"

podman run --rm \
    -v "$SOURCE_DIR:/src:Z" \
    -v "$OUTPUT_DIR:/out:Z" \
    -w /src \
    fedora:44 \
    bash -euc '
        dnf -y -q install \
            c-ares-devel \
            gcc \
            gcc-c++ \
            glib2-devel \
            libphonenumber-devel \
            libsoup3-devel \
            meson \
            mobile-broadband-provider-info \
            ModemManager-glib-devel \
            ninja-build \
            protobuf-devel >/dev/null

        mkdir -p /tmp/pkgconfig
        cat >/tmp/pkgconfig/mobile-broadband-provider-info.pc <<EOF
database=/usr/share/mobile-broadband-provider-info/serviceproviders.xml
Name: mobile-broadband-provider-info
Description: Mobile broadband provider database
Version: 20240407
EOF
        export PKG_CONFIG_PATH=/tmp/pkgconfig
        meson setup _build --prefix=/usr
        meson compile -C _build
        meson test -C _build --print-errorlogs
        cp _build/mmsdtng _build/tools/decode-mms /out/
    '

install -m 755 "$OUTPUT_DIR/mmsdtng" "$INSTALL_DIR/mmsdtng"
install -m 755 "$OUTPUT_DIR/decode-mms" "$INSTALL_DIR/decode-mms"
"$INSTALL_DIR/mmsdtng" --version
