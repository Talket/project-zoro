"""Built-in secure file and report tools for PROJECT ZORO."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from zoro.security.permissions import PermissionGate
from zoro.tools.base import BaseTool, ToolContext, ToolPermissionTier


# ---------------------------------------------------------
# 1. File Discovery Tool (READ_ONLY)
# ---------------------------------------------------------
class FileDiscoveryInput(BaseModel):
    directory: str = Field(description="Root directory path to search within")
    pattern: str = Field(default="*", description="Glob pattern to match, e.g. '*.pdf'")
    max_results: int = Field(default=50, ge=1, le=500, description="Maximum number of files to return")


class DiscoveredFile(BaseModel):
    name: str
    path: str
    size_bytes: int
    modified_at: str


class FileDiscoveryOutput(BaseModel):
    directory: str
    pattern: str
    files: List[DiscoveredFile]
    count: int


class FileDiscoveryTool(BaseTool):
    name = "file_discovery"
    title = "File Discovery"
    description = "Searches for files matching a pattern within a permitted user directory."
    permission_tier = ToolPermissionTier.READ_ONLY
    input_schema = FileDiscoveryInput
    output_schema = FileDiscoveryOutput

    def __init__(self, permission_gate: Optional[PermissionGate] = None) -> None:
        self.gate = permission_gate or PermissionGate()

    async def execute(self, params: FileDiscoveryInput, context: ToolContext) -> FileDiscoveryOutput:
        target_dir = Path(params.directory).resolve()
        if not target_dir.exists() or not target_dir.is_dir():
            raise FileNotFoundError(f"Target directory '{params.directory}' does not exist or is not a directory.")

        if self.gate.is_protected_path(target_dir):
            raise PermissionError(f"Access to protected directory '{target_dir}' is blocked.")

        results: List[DiscoveredFile] = []
        for p in target_dir.glob(params.pattern):
            if p.is_file():
                if self.gate.is_protected_path(p):
                    continue
                stat = p.stat()
                results.append(
                    DiscoveredFile(
                        name=p.name,
                        path=str(p),
                        size_bytes=stat.st_size,
                        modified_at=str(stat.st_mtime),
                    )
                )
                if len(results) >= params.max_results:
                    break

        return FileDiscoveryOutput(
            directory=str(target_dir),
            pattern=params.pattern,
            files=results,
            count=len(results),
        )


# ---------------------------------------------------------
# 2. File Metadata Tool (READ_ONLY)
# ---------------------------------------------------------
class FileMetadataInput(BaseModel):
    file_path: str = Field(description="Path to the file to inspect")


class FileMetadataOutput(BaseModel):
    name: str
    path: str
    size_bytes: int
    extension: str
    exists: bool
    is_file: bool
    modified_at: str


class FileReadMetadataTool(BaseTool):
    name = "file_read_metadata"
    title = "Read File Metadata"
    description = "Retrieves file metadata (size, extension, modified time) without reading contents."
    permission_tier = ToolPermissionTier.READ_ONLY
    input_schema = FileMetadataInput
    output_schema = FileMetadataOutput

    def __init__(self, permission_gate: Optional[PermissionGate] = None) -> None:
        self.gate = permission_gate or PermissionGate()

    async def execute(self, params: FileMetadataInput, context: ToolContext) -> FileMetadataOutput:
        path = Path(params.file_path).resolve()
        if self.gate.is_protected_path(path):
            raise PermissionError(f"Access to protected file '{path}' is blocked.")
        if not path.exists():
            raise FileNotFoundError(f"File '{params.file_path}' does not exist.")

        stat = path.stat()
        return FileMetadataOutput(
            name=path.name,
            path=str(path),
            size_bytes=stat.st_size,
            extension=path.suffix.lower(),
            exists=True,
            is_file=path.is_file(),
            modified_at=str(stat.st_mtime),
        )


# ---------------------------------------------------------
# 3. Report Generator Tool (LOW_RISK)
# ---------------------------------------------------------
class ReportGeneratorInput(BaseModel):
    output_path: str = Field(description="Target file path for the generated report")
    title: str = Field(description="Title of the report")
    content: str = Field(description="Markdown or text content of the report")


class ReportGeneratorOutput(BaseModel):
    written_path: str
    bytes_written: int
    success: bool


class ReportGeneratorTool(BaseTool):
    name = "report_generator"
    title = "Report Generator"
    description = "Generates and saves a structured report document to an authorized location."
    permission_tier = ToolPermissionTier.LOW_RISK
    input_schema = ReportGeneratorInput
    output_schema = ReportGeneratorOutput

    def __init__(self, permission_gate: Optional[PermissionGate] = None) -> None:
        self.gate = permission_gate or PermissionGate()

    async def execute(self, params: ReportGeneratorInput, context: ToolContext) -> ReportGeneratorOutput:
        path = Path(params.output_path).resolve()
        if self.gate.is_protected_path(path):
            raise PermissionError(f"Cannot overwrite protected security path '{path}'.")

        path.parent.mkdir(parents=True, exist_ok=True)
        header = f"# {params.title}\n\n"
        full_content = header + params.content
        path.write_text(full_content, encoding="utf-8")

        return ReportGeneratorOutput(
            written_path=str(path),
            bytes_written=len(full_content.encode("utf-8")),
            success=True,
        )


# ---------------------------------------------------------
# 4. File Move Tool (SENSITIVE)
# ---------------------------------------------------------
class FileMoveInput(BaseModel):
    source_path: str = Field(description="Path of file to move/rename")
    destination_path: str = Field(description="Target destination path")


class FileMoveOutput(BaseModel):
    source_path: str
    destination_path: str
    success: bool


class FileMoveTool(BaseTool):
    name = "file_move"
    title = "File Move & Rename"
    description = "Moves or renames a user file. Classified as SENSITIVE, requires user approval."
    permission_tier = ToolPermissionTier.SENSITIVE
    input_schema = FileMoveInput
    output_schema = FileMoveOutput

    def __init__(self, permission_gate: Optional[PermissionGate] = None) -> None:
        self.gate = permission_gate or PermissionGate()

    async def execute(self, params: FileMoveInput, context: ToolContext) -> FileMoveOutput:
        src = Path(params.source_path).resolve()
        dst = Path(params.destination_path).resolve()

        if self.gate.is_protected_path(src) or self.gate.is_protected_path(dst):
            raise PermissionError("Moving to or from protected security paths is permanently blocked.")
        if not src.exists():
            raise FileNotFoundError(f"Source file '{params.source_path}' does not exist.")

        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)
        return FileMoveOutput(
            source_path=str(src),
            destination_path=str(dst),
            success=True,
        )


# ---------------------------------------------------------
# 5. File Delete Tool (DESTRUCTIVE)
# ---------------------------------------------------------
class FileDeleteInput(BaseModel):
    file_path: str = Field(description="Path of the file to permanently delete")


class FileDeleteOutput(BaseModel):
    deleted_path: str
    success: bool


class FileDeleteTool(BaseTool):
    name = "file_delete"
    title = "File Deletion"
    description = "Permanently deletes a file. Classified as DESTRUCTIVE, requires explicit approval."
    permission_tier = ToolPermissionTier.DESTRUCTIVE
    input_schema = FileDeleteInput
    output_schema = FileDeleteOutput

    def __init__(self, permission_gate: Optional[PermissionGate] = None) -> None:
        self.gate = permission_gate or PermissionGate()

    async def execute(self, params: FileDeleteInput, context: ToolContext) -> FileDeleteOutput:
        path = Path(params.file_path).resolve()
        if self.gate.is_protected_path(path):
            raise PermissionError(f"Deleting protected security file '{path}' is strictly blocked.")
        if not path.exists():
            raise FileNotFoundError(f"Target file '{params.file_path}' does not exist.")

        path.unlink()
        return FileDeleteOutput(deleted_path=str(path), success=True)
