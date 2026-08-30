from __future__ import annotations

import os
import stat
from pathlib import Path

from .native_qa_common import NativeQaError


def lexical_absolute(value: Path) -> Path:
    """Return an absolute, lexically normalized path without resolving links."""

    return Path(os.path.abspath(os.fspath(value.expanduser())))


def is_link_or_reparse(path: Path) -> bool:
    """Detect symbolic links and Windows reparse points without following them."""

    try:
        info = path.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return bool(attributes & reparse_flag)


def canonical_non_link_directory(path: Path, *, label: str) -> tuple[Path, Path]:
    requested = lexical_absolute(path)
    if is_link_or_reparse(requested):
        raise NativeQaError(f"{label} may not itself be a symbolic link or reparse point")
    try:
        actual = requested.resolve(strict=True)
    except OSError as error:
        raise NativeQaError(f"{label} does not exist") from error
    if not actual.is_dir():
        raise NativeQaError(f"{label} must be a directory")
    return requested, actual


def relative_inside(root: Path, candidate: Path, *, label: str) -> str:
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise NativeQaError(f"{label} escapes the admitted root") from error
    if relative == Path("."):
        raise NativeQaError(f"{label} may not be the admitted root itself")
    return relative.as_posix()


def reject_link_components(root: Path, candidate: Path, *, label: str) -> None:
    if candidate == root:
        return
    relative = Path(relative_inside(root, candidate, label=label))
    current = root
    for part in relative.parts:
        current = current / part
        if os.path.lexists(current) and is_link_or_reparse(current):
            raise NativeQaError(
                f"{label} may not traverse symbolic links or reparse points"
            )


def _candidate(
    requested_root: Path,
    actual_root: Path,
    value: Path,
    *,
    label: str,
) -> tuple[Path, str]:
    raw = value.expanduser()
    if not raw.is_absolute():
        requested = lexical_absolute(actual_root / raw)
    else:
        lexical = lexical_absolute(raw)
        try:
            alias_relative = lexical.relative_to(requested_root)
        except ValueError:
            requested = lexical
        else:
            requested = lexical_absolute(actual_root / alias_relative)
    relative = relative_inside(actual_root, requested, label=label)
    return requested, relative


def _prepare_directory_tree(root: Path, directory: Path, *, label: str) -> None:
    relative = Path(relative_inside(root, directory, label=label)) if directory != root else Path()
    current = root
    for part in relative.parts:
        current = current / part
        if os.path.lexists(current):
            if is_link_or_reparse(current):
                raise NativeQaError(
                    f"{label} may not traverse symbolic links or reparse points"
                )
            if not current.is_dir():
                raise NativeQaError(f"{label} contains a non-directory component")
        else:
            try:
                current.mkdir(mode=0o700)
            except OSError as error:
                raise NativeQaError(f"could not create {label}") from error
            if is_link_or_reparse(current) or not current.is_dir():
                raise NativeQaError(f"{label} was replaced while it was created")


def confined_regular_file(
    root_path: Path,
    candidate_path: Path,
    *,
    label: str,
    minimum_bytes: int = 1,
    maximum_bytes: int,
) -> tuple[Path, str, int]:
    if (
        isinstance(minimum_bytes, bool)
        or not isinstance(minimum_bytes, int)
        or minimum_bytes < 0
        or isinstance(maximum_bytes, bool)
        or not isinstance(maximum_bytes, int)
        or maximum_bytes < max(1, minimum_bytes)
        or maximum_bytes > 64 * 1024 * 1024 * 1024
    ):
        raise NativeQaError("evidence file byte limits are outside policy")
    requested_root, root = canonical_non_link_directory(root_path, label="artifact root")
    requested, relative = _candidate(
        requested_root,
        root,
        candidate_path,
        label=label,
    )
    reject_link_components(root, requested, label=label)
    try:
        actual = requested.resolve(strict=True)
    except OSError as error:
        raise NativeQaError(f"{label} does not exist") from error
    actual_relative = relative_inside(root, actual, label=label)
    if actual_relative != relative or not actual.is_file():
        raise NativeQaError(f"{label} is not a canonical regular file")
    size = actual.stat().st_size
    if not minimum_bytes <= size <= maximum_bytes:
        raise NativeQaError(f"{label} size is outside policy")
    return actual, actual_relative, size


def confined_output_file(
    root_path: Path,
    candidate_path: Path,
    *,
    label: str,
    required_suffix: str | None = None,
) -> tuple[Path, str]:
    requested_root, root = canonical_non_link_directory(root_path, label="artifact root")
    requested, relative = _candidate(
        requested_root,
        root,
        candidate_path,
        label=label,
    )
    if required_suffix is not None and requested.suffix.lower() != required_suffix.lower():
        raise NativeQaError(f"{label} must use a {required_suffix} suffix")
    _prepare_directory_tree(root, requested.parent, label=f"{label} parent")
    reject_link_components(root, requested.parent, label=f"{label} parent")
    actual_parent = requested.parent.resolve(strict=True)
    parent_relative = (
        relative_inside(root, actual_parent, label=f"{label} parent")
        if actual_parent != root
        else ""
    )
    expected_parent = (
        requested.parent.relative_to(root).as_posix()
        if requested.parent != root
        else ""
    )
    if parent_relative != expected_parent:
        raise NativeQaError(f"{label} parent is not canonical")
    if os.path.lexists(requested):
        raise NativeQaError(f"refusing to overwrite an existing {label}")
    return requested, relative
