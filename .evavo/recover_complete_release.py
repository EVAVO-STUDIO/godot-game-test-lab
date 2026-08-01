from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import stat
import tarfile
from pathlib import Path, PurePosixPath

ARCHIVE_BYTES = 114_059
ARCHIVE_SHA256 = "c6a6ed63d7fe8078591430c2a0fb93c066bf37b3e5347f8c5744cd2d2891ce51"
TEMPORARY_PATHS = (
    ".evavo/bootstrap",
    ".evavo/agent-audio-upgrade-diagnostic.txt",
    ".evavo/managed-sandbox-0.7-diagnostic.txt",
    ".evavo/managed-sandbox-release-pr.txt",
    ".evavo/recover_complete_release.py",
    ".github/workflows/apply-agent-audio-upgrade.yml",
    ".github/workflows/apply-managed-sandbox-0.7.yml",
    ".github/workflows/dispatch-agent-audio-upgrade.yml",
)


def fail(message: str) -> None:
    raise SystemExit(message)


def safe_relative(value: str) -> PurePosixPath:
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        fail(f"unsafe release path: {value}")
    return pure


def remove_path(root: Path, relative: str) -> None:
    path = root.joinpath(*PurePosixPath(relative).parts)
    if path.is_symlink():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def main() -> int:
    root = Path.cwd().resolve(strict=True)
    runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    stage = runner_temp / "final-source-tree"
    if stage.exists() or stage.is_symlink():
        fail(f"staging path already exists: {stage}")

    for directory, names, filenames in os.walk(root, topdown=True, followlinks=False):
        current = Path(directory)
        if current == root / ".git" or (root / ".git") in current.parents:
            names[:] = []
            continue
        for name in [*names, *filenames]:
            path = current / name
            if path.is_symlink():
                fail(f"source checkout contains a symbolic link: {path.relative_to(root)}")

    shutil.copytree(
        root,
        stage,
        ignore=shutil.ignore_patterns(
            ".git",
            "final-source.tar.gz",
            "final-tree-receipt.json",
            "overlay-receipt.json",
        ),
    )

    manifest_path = root / ".evavo/bootstrap/managed-sandbox-0.7.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = manifest.get("files")
    if manifest.get("schemaVersion") != "1.0" or manifest.get("releaseVersion") != "0.7.0":
        fail("unexpected release manifest identity")
    if not isinstance(records, list) or len(records) != 52:
        fail("unexpected release manifest inventory")

    expected: dict[str, dict[str, object]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            fail("invalid release file record")
        name = record["path"]
        safe_relative(name)
        if name in expected:
            fail(f"duplicate release path: {name}")
        expected[name] = record

    encoded_parts: list[str] = []
    for number in range(22):
        relative = Path(f".evavo/bootstrap/managed-sandbox-0.7-small-{number:03d}.b64")
        path = root / relative
        if path.is_symlink() or not path.is_file() or path.resolve(strict=True) != path.absolute():
            fail(f"missing or unsafe release segment: {relative}")
        compact = "".join(path.read_text(encoding="ascii").split())
        if not compact or re.fullmatch(r"[A-Za-z0-9+/]*={0,2}", compact) is None:
            fail(f"invalid Base64 release segment: {relative}")
        if number < 21 and "=" in compact:
            fail(f"non-final release segment contains padding: {relative}")
        encoded_parts.append(compact)

    archive_bytes = base64.b64decode("".join(encoded_parts), validate=True)
    archive_sha = hashlib.sha256(archive_bytes).hexdigest()
    if len(archive_bytes) != ARCHIVE_BYTES or archive_sha != ARCHIVE_SHA256:
        fail(f"archive identity mismatch: bytes={len(archive_bytes)} sha256={archive_sha}")
    if manifest.get("archiveBytes") != ARCHIVE_BYTES or manifest.get("archiveSha256") != ARCHIVE_SHA256:
        fail("manifest archive identity mismatch")

    archive_path = runner_temp / "managed-sandbox-0.7.tar.gz"
    archive_path.write_bytes(archive_bytes)
    observed: set[str] = set()
    expanded = 0
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = archive.getmembers()
        if len(members) != len(expected):
            fail("release archive member count mismatch")
        for member in members:
            pure = safe_relative(member.name)
            record = expected.get(member.name)
            if (
                not member.isfile()
                or member.name in observed
                or record is None
                or member.size != record.get("bytes")
                or member.size < 0
                or member.size > 4 * 1024 * 1024
            ):
                fail(f"unsafe release archive member: {member.name}")
            observed.add(member.name)
            expanded += member.size
            destination = stage.joinpath(*pure.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.parent.resolve(strict=True).relative_to(stage.resolve(strict=True))
            if destination.is_symlink():
                fail(f"release destination may not be a symbolic link: {member.name}")
            source = archive.extractfile(member)
            if source is None:
                fail(f"unreadable release archive member: {member.name}")
            data = source.read(int(record["bytes"]) + 1)
            if len(data) != record["bytes"]:
                fail(f"release member read-size mismatch: {member.name}")
            if hashlib.sha256(data).hexdigest() != record["sha256"]:
                fail(f"release member checksum mismatch: {member.name}")
            destination.write_bytes(data)
            mode = int(str(record["mode"]), 8)
            destination.chmod(mode)
            if stat.S_IMODE(destination.stat().st_mode) != mode:
                fail(f"release member mode mismatch: {member.name}")
    if observed != set(expected) or expanded > 8 * 1024 * 1024:
        fail("release archive contract mismatch")

    for relative in TEMPORARY_PATHS:
        remove_path(stage, relative)

    files: list[dict[str, object]] = []
    for directory, names, filenames in os.walk(stage, topdown=True, followlinks=False):
        current = Path(directory)
        names[:] = sorted(names)
        for name in sorted(filenames):
            path = current / name
            relative = path.relative_to(stage).as_posix()
            if path.is_symlink() or not path.is_file():
                fail(f"unsafe final source entry: {relative}")
            data = path.read_bytes()
            files.append(
                {
                    "path": relative,
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "mode": oct(stat.S_IMODE(path.stat().st_mode)),
                }
            )

    final_receipt = {
        "schemaVersion": "1.0",
        "releaseVersion": "0.7.0",
        "sourceCommit": os.environ.get("GITHUB_SHA"),
        "archiveBytes": ARCHIVE_BYTES,
        "archiveSha256": ARCHIVE_SHA256,
        "overlayFileCount": len(expected),
        "fileCount": len(files),
        "files": files,
    }
    Path("final-tree-receipt.json").write_text(
        json.dumps(final_receipt, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    Path("overlay-receipt.json").write_text(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "releaseVersion": "0.7.0",
                "archiveBytes": ARCHIVE_BYTES,
                "archiveSha256": ARCHIVE_SHA256,
                "fileCount": len(expected),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"prepared {len(files)} final files from {len(expected)} verified overlay files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
