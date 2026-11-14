"""Read-only text file access confined to the workspace sandbox.

Security model:
- Root is `WORKSPACE_DIR`; an agent may narrow it with `subdir`, never widen it.
- Paths from the model must be relative. The final path is fully resolved
  (following symlinks) and must stay inside the allowed base folder.
- Only regular, UTF-8, NUL-free files up to MAX_BYTES are returned.
- Error messages never reveal absolute host paths.
"""

import asyncio
import re
from pathlib import Path, PurePath
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.tools.base import Tool, ToolContext, ToolError

MAX_BYTES = 100_000


_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


def _is_unsafe_relative(value: str) -> bool:
    """True for absolute paths, drive-qualified paths (on any OS) and '..' components."""
    normalized = value.replace("\\", "/")
    p = PurePath(normalized)
    return (
        p.is_absolute()
        or bool(p.anchor)
        or normalized.startswith("/")
        or bool(_WINDOWS_DRIVE.match(normalized))
        or ".." in p.parts
    )


class FileReaderArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        min_length=1,
        max_length=500,
        description="Path of a text file relative to the workspace folder, e.g. 'notes.txt'",
    )


class FileReaderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subdir: str = Field(
        default="",
        max_length=300,
        title="Subfolder",
        description=(
            "Limit this agent to a subfolder of the workspace. Leave empty for the whole workspace."
        ),
        examples=["notes"],
    )

    @field_validator("subdir")
    @classmethod
    def _relative_inside_workspace(cls, v: str) -> str:
        v = v.strip()
        if v and _is_unsafe_relative(v):
            raise ValueError("must be a relative path inside the workspace without '..'")
        return v.replace("\\", "/").strip("/")


def _read_text_file(target: Path, display: str) -> str:
    if not target.is_file():
        raise ToolError(f"File not found: {display}")
    if target.stat().st_size > MAX_BYTES:
        raise ToolError(f"File is too large (max {MAX_BYTES} bytes): {display}")
    data = target.read_bytes()
    if len(data) > MAX_BYTES:  # file grew after stat()
        raise ToolError(f"File is too large (max {MAX_BYTES} bytes): {display}")
    if b"\x00" in data:
        raise ToolError(f"Binary files are not supported: {display}")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise ToolError(f"File is not UTF-8 text: {display}") from None


def resolve_in_sandbox(workspace_dir: Path, subdir: str, path: str) -> Path:
    """Return the resolved target path, or raise ToolError if it leaves the sandbox."""
    root = workspace_dir.resolve()
    base = (root / subdir).resolve()
    if not base.is_relative_to(root) or not base.is_dir():
        raise ToolError("The configured workspace folder is not available")
    if _is_unsafe_relative(path):
        raise ToolError("Path must be relative to the workspace and must not contain '..'")
    # Check and use the same normalized form, so '\' behaves identically on every OS.
    target = (base / path.replace("\\", "/")).resolve()  # follows symlinks
    if not target.is_relative_to(base):
        raise ToolError("Access outside the workspace is not allowed")
    return target


class FileReaderTool(Tool[FileReaderArgs, FileReaderConfig]):
    name: ClassVar[str] = "file_reader"
    description: ClassVar[str] = (
        "Read a UTF-8 text file from the user's workspace folder. "
        "Takes a path relative to the workspace."
    )
    args_model = FileReaderArgs
    config_model = FileReaderConfig
    timeout_s = 5.0

    async def run(self, args: FileReaderArgs, config: FileReaderConfig, ctx: ToolContext) -> str:
        target = resolve_in_sandbox(ctx.workspace_dir, config.subdir, args.path)
        return await asyncio.to_thread(_read_text_file, target, args.path)
