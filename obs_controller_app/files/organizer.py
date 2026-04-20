"""Move and rename finished recordings and clips into managed folders."""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


class FileOrganizer:
    """Renames files as ``{prefix} {n}.ext`` without overwriting existing files."""

    def __init__(
        self,
        *,
        final_recordings_folder: Path,
        final_clips_folder: Path,
        recording_prefix: str,
        clip_prefix: str,
        video_extensions: tuple[str, ...],
    ) -> None:
        self._rec_dir = final_recordings_folder
        self._clip_dir = final_clips_folder
        self._recording_prefix = recording_prefix
        self._clip_prefix = clip_prefix
        self._exts = video_extensions

    def _numbered_pattern(self, prefix: str) -> re.Pattern[str]:
        # Example: "Recordings 12.mp4"
        return re.compile(rf"^{re.escape(prefix)} (\d+)\.[^.]+$", re.IGNORECASE)

    def get_next_number(self, folder: Path, *, name_prefix: str) -> int:
        """Scan ``folder`` for ``{name_prefix} {n}.ext`` and return max(n)+1 (or 1)."""
        folder.mkdir(parents=True, exist_ok=True)
        pat = self._numbered_pattern(name_prefix)
        highest = 0
        for p in folder.iterdir():
            if not p.is_file():
                continue
            m = pat.match(p.name)
            if m:
                highest = max(highest, int(m.group(1)))
        return highest + 1

    def _pick_unique_dest(self, folder: Path, prefix: str, src_suffix: str) -> Path:
        n = self.get_next_number(folder, name_prefix=prefix)
        while True:
            candidate = folder / f"{prefix} {n}{src_suffix.lower()}"
            if not candidate.exists():
                return candidate
            n += 1

    def move_and_rename_recording(self, src_path: Path) -> Path:
        """Move a finished recording into the final recordings folder with the next index."""
        if not src_path.is_file():
            raise FileNotFoundError(f"Recording source missing: {src_path}")
        dest = self._pick_unique_dest(self._rec_dir, self._recording_prefix, src_path.suffix)
        self._rec_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Moving recording %s -> %s", src_path, dest)
        shutil.move(str(src_path), str(dest))
        return dest

    def move_and_rename_clip(self, src_path: Path) -> Path:
        """
        Move a clip into the final clips folder.

        Reserved for replay-buffer / clip workflows; same numbering rules as recordings.
        """
        if not src_path.is_file():
            raise FileNotFoundError(f"Clip source missing: {src_path}")
        dest = self._pick_unique_dest(self._clip_dir, self._clip_prefix, src_path.suffix)
        self._clip_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Moving clip %s -> %s", src_path, dest)
        shutil.move(str(src_path), str(dest))
        return dest

    def delete_file(self, path: Path) -> None:
        """Delete a file if it exists; raises OSError on failure."""
        if not path.is_file():
            raise FileNotFoundError(f"Cannot delete missing file: {path}")
        logger.info("Deleting file: %s", path)
        path.unlink()
