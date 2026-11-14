import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.tools.base import ToolContext, ToolError
from app.tools.file_reader import MAX_BYTES, FileReaderConfig, FileReaderTool


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """tmp/
    secret.txt        <- outside the workspace
    ws/notes.txt
    ws/sub/inner.txt
    ws/big.txt, ws/binary.bin, ws/latin1.txt
    """
    (tmp_path / "secret.txt").write_text("TOP SECRET", encoding="utf-8")
    ws = tmp_path / "ws"
    (ws / "sub").mkdir(parents=True)
    (ws / "notes.txt").write_text("hello notes", encoding="utf-8")
    (ws / "sub" / "inner.txt").write_text("inner", encoding="utf-8")
    (ws / "big.txt").write_bytes(b"a" * (MAX_BYTES + 1))
    (ws / "binary.bin").write_bytes(b"\x89PNG\x00\x01")
    (ws / "latin1.txt").write_bytes("café".encode("latin-1"))
    return ws


async def read(ws: Path, path: str, subdir: str = "") -> str:
    tool = FileReaderTool()
    return await tool.run(
        tool.parse_args({"path": path}),
        tool.parse_config({"subdir": subdir}),
        ToolContext(workspace_dir=ws),
    )


async def test_reads_file_in_workspace(sandbox: Path) -> None:
    assert await read(sandbox, "notes.txt") == "hello notes"
    assert await read(sandbox, "sub/inner.txt") == "inner"
    assert await read(sandbox, "sub\\inner.txt") == "inner"
    assert await read(sandbox, "./notes.txt") == "hello notes"


async def test_reads_within_configured_subdir(sandbox: Path) -> None:
    assert await read(sandbox, "inner.txt", subdir="sub") == "inner"


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("../secret.txt", "must not contain '..'"),
        ("sub/../../secret.txt", "must not contain '..'"),
        ("..\\secret.txt", "must not contain '..'"),
        ("missing.txt", "File not found"),
        ("sub", "File not found"),
        ("big.txt", "too large"),
        ("binary.bin", "Binary files"),
        ("latin1.txt", "not UTF-8"),
    ],
)
async def test_rejections(sandbox: Path, path: str, message: str) -> None:
    with pytest.raises(ToolError, match=message):
        await read(sandbox, path)


async def test_rejects_absolute_paths(sandbox: Path) -> None:
    outside = str((sandbox.parent / "secret.txt").resolve())
    inside = str((sandbox / "notes.txt").resolve())
    for path in (outside, inside, "/etc/passwd", "C:/Windows/win.ini", "C:notes.txt"):
        with pytest.raises(ToolError, match="must be relative"):
            await read(sandbox, path)


async def test_subdir_cannot_reach_parent_files(sandbox: Path) -> None:
    with pytest.raises(ToolError):
        await read(sandbox, "notes.txt", subdir="sub")
    with pytest.raises(ToolError, match="must not contain"):
        await read(sandbox, "../notes.txt", subdir="sub")


async def test_missing_subdir_is_reported_without_host_path(sandbox: Path) -> None:
    with pytest.raises(ToolError) as exc:
        await read(sandbox, "x.txt", subdir="nope")
    assert str(sandbox) not in str(exc.value)


async def test_error_messages_do_not_leak_host_paths(sandbox: Path) -> None:
    with pytest.raises(ToolError) as exc:
        await read(sandbox, "missing.txt")
    assert str(sandbox) not in str(exc.value)
    assert "missing.txt" in str(exc.value)


def _symlink_or_skip(link: Path, target: Path, *, is_dir: bool = False) -> None:
    try:
        os.symlink(target, link, target_is_directory=is_dir)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this system (Windows needs Developer Mode)")


async def test_symlink_escape_is_blocked(sandbox: Path) -> None:
    _symlink_or_skip(sandbox / "link.txt", sandbox.parent / "secret.txt")
    with pytest.raises(ToolError, match="outside the workspace"):
        await read(sandbox, "link.txt")


async def test_symlinked_directory_escape_is_blocked(sandbox: Path) -> None:
    _symlink_or_skip(sandbox / "linkdir", sandbox.parent, is_dir=True)
    with pytest.raises(ToolError, match="outside the workspace"):
        await read(sandbox, "linkdir/secret.txt")


@pytest.mark.parametrize("subdir", ["../x", "/abs", "C:/x", "a/../../b", "..\\x"])
def test_config_rejects_unsafe_subdir(subdir: str) -> None:
    with pytest.raises(ValidationError):
        FileReaderConfig(subdir=subdir)


@pytest.mark.parametrize(("raw", "normalized"), [("", ""), ("notes/", "notes"), ("a\\b", "a/b")])
def test_config_normalizes_subdir(raw: str, normalized: str) -> None:
    assert FileReaderConfig(subdir=raw).subdir == normalized
