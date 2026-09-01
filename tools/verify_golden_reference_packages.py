#!/usr/bin/env python3
"""Verify frozen FABINZI Golden Reference package identity and archive integrity.

This tool intentionally verifies binary identity/ZIP integrity only. It does not
claim semantic acceptance of Golden product contents; V2-4 requires direct
semantic inspection of the five verified packages before Golden integration can
be accepted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath

EXPECTED_PRODUCTS = {
    "GP001": (
        "FABINZI_GP001_Golden_Reference_v1.0.zip",
        "acece3e05f13143624e805d1e9ea57b494e0e1d58120d833144565c47e2f9edf",
    ),
    "GP002": (
        "FABINZI_GP002_Golden_Reference_v1.0.zip",
        "a8f44ab55eda7bab03b0dd5a92a71dd62b794d81f2e89ae7c37633062a24123e",
    ),
    "GP003": (
        "FABINZI_GP003_Golden_Reference_v1.0.zip",
        "7fee3a6362bdaa0fbd0c03f2c2a42234d960228405dd4946e40fc20d8ff6a463",
    ),
    "GP004": (
        "FABINZI_GP004_Golden_Reference_v1.0.zip",
        "b05405620189e7c9f8d564db3650a683880a9ca1670124fc7266713ead1ed75f",
    ),
    "GP005": (
        "FABINZI_GP005_Golden_Reference_v1.0.zip",
        "39fdc2beb5fa38476f42235c1e11931309f73655c9fa88ee254626518d09c19c",
    ),
}
EXPECTED_CONTRACT_HASHES = {
    "golden_product_machine_contract_v1_0": "46235ca6f221575c45645a1388ffa410e331320470508d8cf8374f7c02616a6f",
    "golden_image_role_qa_contract_v1_0": "74f4fb0a388ace493b06cfb6c68e7c4a8b61d73bce1b82a3c7d44fca9b3b0176",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_and_validate_manifest(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("contract") != "FABINZI_GOLDEN_REFERENCE_INTEGRITY_V1":
        raise ValueError("unexpected Golden integrity contract identity")
    if data.get("version") != "1.0":
        raise ValueError("unexpected Golden integrity contract version")

    products = data.get("products")
    if not isinstance(products, list) or len(products) != 5:
        raise ValueError("Golden integrity contract must contain exactly five products")

    actual = {}
    for item in products:
        ref = item.get("product_ref")
        filename = item.get("filename")
        digest = item.get("sha256")
        if ref in actual:
            raise ValueError(f"duplicate product_ref: {ref}")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise ValueError(f"invalid SHA-256 for {ref}")
        actual[ref] = (filename, digest)

    if actual != EXPECTED_PRODUCTS:
        raise ValueError("Golden product filenames or frozen SHA-256 values differ from the V2 Architecture Freeze")

    contract_hashes = data.get("frozen_contract_sha256")
    if contract_hashes != EXPECTED_CONTRACT_HASHES:
        raise ValueError("Golden frozen contract hashes differ from the V2 Architecture Freeze")

    policy = data.get("policy") or {}
    required_true = (
        "binary_verification_required_before_import_acceptance",
        "semantic_validation_required_before_v2_4_acceptance",
        "reference_approval_is_not_production_approval",
    )
    if not all(policy.get(key) is True for key in required_true):
        raise ValueError("Golden verification policy must preserve all frozen evidence gates")

    return data


def validate_archive(path: Path, expected_sha256: str) -> int:
    if not path.is_file():
        raise FileNotFoundError(f"missing required Golden package: {path}")

    actual_sha256 = sha256_file(path)
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"SHA-256 mismatch for {path.name}: expected {expected_sha256}, got {actual_sha256}"
        )
    if not zipfile.is_zipfile(path):
        raise ValueError(f"not a valid ZIP archive: {path.name}")

    with zipfile.ZipFile(path, "r") as archive:
        infos = archive.infolist()
        if not infos:
            raise ValueError(f"empty ZIP archive: {path.name}")

        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate archive entry names detected: {path.name}")

        for info in infos:
            member = PurePosixPath(info.filename)
            if member.is_absolute() or ".." in member.parts:
                raise ValueError(f"unsafe archive path in {path.name}: {info.filename}")
            if info.flag_bits & 0x1:
                raise ValueError(f"encrypted archive entry is not accepted: {path.name}:{info.filename}")

        bad_member = archive.testzip()
        if bad_member is not None:
            raise ValueError(f"CRC/integrity failure in {path.name}: {bad_member}")

    return len(infos)


def verify_optional_contract(path: Path | None, expected_key: str) -> None:
    if path is None:
        return
    if not path.is_file():
        raise FileNotFoundError(path)
    actual = sha256_file(path)
    expected = EXPECTED_CONTRACT_HASHES[expected_key]
    if actual != expected:
        raise ValueError(
            f"SHA-256 mismatch for {expected_key}: expected {expected}, got {actual}"
        )
    print(f"VERIFIED {expected_key} sha256={actual}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("contracts/golden-reference-v1-integrity.json"),
    )
    parser.add_argument("--packages-dir", type=Path)
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--machine-contract", type=Path)
    parser.add_argument("--image-role-contract", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        load_and_validate_manifest(args.manifest)
        print("VERIFIED Golden integrity metadata against the frozen V2-0 contract")

        if args.metadata_only:
            if args.packages_dir is not None:
                raise ValueError("--metadata-only cannot be combined with --packages-dir")
            if args.machine_contract is not None or args.image_role_contract is not None:
                raise ValueError("--metadata-only cannot verify contract bytes")
            print("Golden package bytes NOT VERIFIED by metadata-only mode")
            return 0

        if args.packages_dir is None:
            raise ValueError("--packages-dir is required for binary Golden package verification")

        for product_ref, (filename, expected_sha256) in EXPECTED_PRODUCTS.items():
            path = args.packages_dir / filename
            entry_count = validate_archive(path, expected_sha256)
            print(
                f"VERIFIED {product_ref} filename={filename} sha256={expected_sha256} entries={entry_count}"
            )

        verify_optional_contract(
            args.machine_contract,
            "golden_product_machine_contract_v1_0",
        )
        verify_optional_contract(
            args.image_role_contract,
            "golden_image_role_qa_contract_v1_0",
        )
        print(
            "All five Golden package byte identities and ZIP structures verified. "
            "Semantic product-content acceptance remains a separate mandatory V2-4 gate."
        )
        return 0
    except (OSError, ValueError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        print(f"GOLDEN VERIFICATION FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
