# SPDX-License-Identifier: MIT
"""
Background render jobs.

A blocking `render_animation` holds the agent hostage for the whole render
and gives no progress, no previews and no way to stop. A job instead renders
frame-by-frame from an asyncio task in this process: each frame is one short
RPC, so other tool calls interleave between frames, progress and an ETA are
always known, cancellation lands at the next frame boundary, and finished
frames can be inspected while the rest render. When every frame is done the
addon encodes them to MP4 in a throwaway scene.

This mirrors the MCP Tasks extension (SEP-2663: start -> poll -> cancel) with
plain tools, so it works with every client today. Jobs live in this process:
behind a multi-replica HTTP deployment they would need a shared store.
"""

import asyncio
import itertools
import os
import tempfile
import time
from dataclasses import dataclass, field
from typing import Optional

from .blender_client import BlenderClient

MAX_FRAMES = 1000
_MAX_JOBS = 20  # finished jobs beyond this are forgotten, oldest first
_FRAME_TIMEOUT = 900.0
_ENCODE_TIMEOUT = 900.0

ACTIVE = ("queued", "rendering", "encoding")


@dataclass
class RenderJob:
    job_id: str
    frames: list[int]
    fps: int
    container: str
    output: str
    frame_dir: str
    render_args: dict
    status: str = "queued"
    error: Optional[str] = None
    done: list[tuple[int, str, float]] = field(default_factory=list)  # (frame, path, seconds)
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    result: Optional[dict] = None
    cancel_requested: bool = False
    task: Optional[asyncio.Task] = None

    @property
    def total(self) -> int:
        return len(self.frames)

    def eta_seconds(self) -> Optional[float]:
        if not self.done or self.status != "rendering":
            return None
        avg = sum(s for _, _, s in self.done) / len(self.done)
        return round(avg * (self.total - len(self.done)), 1)

    def to_status(self) -> dict:
        elapsed = (self.finished_at or time.time()) - self.created_at
        return {
            "job_id": self.job_id,
            "status": self.status,
            "frames_done": len(self.done),
            "frames_total": self.total,
            "percent": round(100.0 * len(self.done) / self.total, 1) if self.total else 0.0,
            "frame_range": [self.frames[0], self.frames[-1]] if self.frames else [],
            "last_frame": self.done[-1][0] if self.done else None,
            "elapsed_seconds": round(elapsed, 1),
            "eta_seconds": self.eta_seconds(),
            "output": self.output if self.status == "completed" else None,
            "frame_dir": self.frame_dir,
            "error": self.error,
        }


class JobManager:
    """Owns render jobs for the lifetime of the MCP server process."""

    def __init__(self):
        self._jobs: dict[str, RenderJob] = {}
        self._ids = itertools.count(1)

    def get(self, job_id: str) -> Optional[RenderJob]:
        return self._jobs.get(job_id)

    def all(self) -> list[RenderJob]:
        return list(self._jobs.values())

    def active(self) -> list[RenderJob]:
        return [j for j in self._jobs.values() if j.status in ACTIVE]

    def start(
        self,
        client: BlenderClient,
        frames: list[int],
        fps: int,
        container: str,
        output: Optional[str],
        render_args: dict,
    ) -> RenderJob:
        job_id = f"job-{next(self._ids)}"
        frame_dir = tempfile.mkdtemp(prefix=f"claude_{job_id}_")
        if container == "PNG":
            output = frame_dir
        else:
            output = os.path.abspath(os.path.expanduser(
                output or os.path.join(tempfile.gettempdir(), f"claude_{job_id}.mp4")
            ))
        job = RenderJob(
            job_id=job_id, frames=frames, fps=fps, container=container,
            output=output, frame_dir=frame_dir, render_args=render_args,
        )
        self._jobs[job_id] = job
        self._prune()
        job.task = asyncio.create_task(self._run(job, client), name=job_id)
        return job

    def cancel(self, job_id: str) -> Optional[RenderJob]:
        job = self._jobs.get(job_id)
        if job is not None and job.status in ACTIVE:
            # Cooperative: the in-flight frame finishes (Blender can't be
            # interrupted mid-render over RPC), then the loop stops.
            job.cancel_requested = True
        return job

    def _prune(self):
        finished = [j for j in self._jobs.values() if j.status not in ACTIVE]
        for job in finished[: max(0, len(self._jobs) - _MAX_JOBS)]:
            del self._jobs[job.job_id]

    async def _run(self, job: RenderJob, client: BlenderClient):
        try:
            job.status = "rendering"
            for frame in job.frames:
                if job.cancel_requested:
                    job.status = "cancelled"
                    return
                path = os.path.join(job.frame_dir, f"frame_{frame:04d}.png")
                started = time.monotonic()
                response = await client.render(
                    filepath=path, frame=frame, timeout=_FRAME_TIMEOUT, **job.render_args
                )
                result = response.get("result") if "error" not in response else None
                if not isinstance(result, dict) or not result.get("success"):
                    reason = (response.get("error") or {}).get("message") if "error" in response \
                        else (result or {}).get("error", "unknown error")
                    raise RuntimeError(f"frame {frame} failed: {reason}")
                job.done.append((frame, path, time.monotonic() - started))

            if job.cancel_requested:
                job.status = "cancelled"
                return

            if job.container == "MP4":
                job.status = "encoding"
                response = await client.call(
                    "encode_video", timeout=_ENCODE_TIMEOUT,
                    frame_paths=[p for _, p, _ in job.done],
                    filepath=job.output, fps=job.fps,
                )
                result = response.get("result") if "error" not in response else None
                if not isinstance(result, dict) or not result.get("success"):
                    reason = (response.get("error") or {}).get("message") if "error" in response \
                        else (result or {}).get("error", "unknown error")
                    raise RuntimeError(f"encoding failed: {reason}")
                job.output = result.get("filepath", job.output)
                job.result = result
            job.status = "completed"
        except Exception as e:  # the job records its own failure; nobody awaits the task
            job.status = "failed"
            job.error = str(e)
        finally:
            job.finished_at = time.time()


def pick_evenly(items: list, n: int) -> list:
    """Up to n items evenly spaced across the list, always including both ends."""
    if n <= 0 or not items:
        return []
    if n >= len(items):
        return list(items)
    if n == 1:
        return [items[-1]]
    span = len(items) - 1
    return [items[round(span * i / (n - 1))] for i in range(n)]
