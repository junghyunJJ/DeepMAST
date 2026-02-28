"""Docker-based sandbox backend for Drug Target Assessment Agent.

Provides true container-level isolation via Docker, replacing the
GuardedLocalExecBackend command-whitelist approach. Implements BaseSandbox
with dual volume mounts (workspace rw + skills ro).

Security model: Docker process isolation — the LLM can modify /workspace
but cannot escape the container. Host filesystem access is limited to
explicitly mounted volumes.
"""

from __future__ import annotations

import io
import logging
import os
import shlex
import tarfile
from pathlib import Path

import docker
from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
    WriteResult,
)
from deepagents.backends.sandbox import BaseSandbox

logger = logging.getLogger(__name__)


class DockerBackend(BaseSandbox):
    """Docker-based sandbox backend with dual volume mounts.

    Mounts:
        host_dir   -> container_dir (rw)  — workspace for data I/O
        skills_dir -> /skills (ro)        — skill definitions

    The container runs ``tail -f /dev/null`` and commands are executed
    via ``container.exec_run()``.
    """

    def __init__(
        self,
        image_name: str = "python:3.12-slim",
        host_dir: str | Path | None = None,
        container_dir: str = "/workspace",
        skills_dir: str | Path | None = None,
    ) -> None:
        self.client = docker.from_env()
        self.container_dir = container_dir
        self._image_name = image_name

        volumes: dict[str, dict[str, str]] = {}
        if host_dir:
            host_dir = str(Path(host_dir).resolve())
            volumes[host_dir] = {"bind": container_dir, "mode": "rw"}
        if skills_dir:
            skills_dir = str(Path(skills_dir).resolve())
            volumes[skills_dir] = {"bind": "/skills", "mode": "ro"}

        logger.info(
            "Starting Docker container (%s) with mounts: %s",
            image_name,
            volumes,
        )

        self.container = self.client.containers.run(
            image_name,
            command="tail -f /dev/null",
            detach=True,
            remove=True,
            volumes=volumes,
            working_dir=container_dir,
        )

        # Install Python dependencies needed by skill scripts
        self.execute("pip install --quiet --disable-pip-version-check requests")

    @property
    def id(self) -> str:
        return self.container.short_id

    def execute(
        self, command: str, *, timeout: int | None = None
    ) -> ExecuteResponse:
        exit_code, output = self.container.exec_run(
            ["/bin/sh", "-c", command],
        )
        decoded = output.decode("utf-8") if isinstance(output, bytes) else output
        return ExecuteResponse(output=decoded, exit_code=exit_code)

    def write(self, file_path: str, content: str) -> WriteResult:
        """Write a file, removing any existing file first.

        BaseSandbox.write() rejects existing files. This override removes
        the target first to support overwrites during re-runs and quality
        iteration loops.
        """
        self.execute(f"rm -f {shlex.quote(file_path)}")
        return super().write(file_path, content)

    def upload_files(
        self, files: list[tuple[str, bytes]]
    ) -> list[FileUploadResponse]:
        """Upload files to the container preserving full directory structure."""
        results: list[FileUploadResponse] = []
        for path, content in files:
            try:
                tar_stream = io.BytesIO()
                with tarfile.open(fileobj=tar_stream, mode="w") as tar:
                    info = tarfile.TarInfo(name=path.lstrip("/"))
                    info.size = len(content)
                    tar.addfile(info, io.BytesIO(content))
                tar_stream.seek(0)
                self.container.put_archive("/", tar_stream)
                results.append(FileUploadResponse(path=path))
            except Exception:
                logger.exception("Failed to upload %s", path)
                results.append(
                    FileUploadResponse(path=path, error="permission_denied")
                )
        return results

    def download_files(
        self, paths: list[str]
    ) -> list[FileDownloadResponse]:
        """Download files from the container."""
        results: list[FileDownloadResponse] = []
        for path in paths:
            try:
                bits, _ = self.container.get_archive(path)
                stream = io.BytesIO(b"".join(bits))
                with tarfile.open(fileobj=stream) as tar:
                    member = tar.getmembers()[0]
                    f = tar.extractfile(member)
                    if f is None:
                        results.append(
                            FileDownloadResponse(
                                path=path, error="is_directory"
                            )
                        )
                        continue
                    file_content = f.read()
                results.append(
                    FileDownloadResponse(path=path, content=file_content)
                )
            except Exception:
                logger.exception("Failed to download %s", path)
                results.append(
                    FileDownloadResponse(path=path, error="file_not_found")
                )
        return results

    def cleanup(self) -> None:
        """Stop and remove the container."""
        try:
            self.container.stop(timeout=5)
        except Exception:
            logger.debug("Container already stopped or removed", exc_info=True)

    def __enter__(self) -> DockerBackend:
        return self

    def __exit__(self, *exc: object) -> None:
        self.cleanup()
