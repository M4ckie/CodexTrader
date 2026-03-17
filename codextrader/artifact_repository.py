"""Read-only access helpers for persisted run artifacts."""

from __future__ import annotations

from pathlib import Path

from .artifacts import ExecutionReportArtifact, SchedulerStatusArtifact, read_json_file


class ArtifactRepository:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    def _execution_paths(self) -> list[Path]:
        return sorted(
            self.output_dir.glob("**/daily_execution.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )

    def find_latest_execution(self, scenario_name: str) -> tuple[ExecutionReportArtifact | None, Path | None]:
        for path in self._execution_paths():
            payload = ExecutionReportArtifact.from_dict(read_json_file(path))
            if payload.scenario == scenario_name:
                return payload, path
        return None, None

    def load_execution_history(self, scenario_name: str) -> list[tuple[ExecutionReportArtifact, Path]]:
        history: list[tuple[ExecutionReportArtifact, Path]] = []
        for path in self._execution_paths():
            payload = ExecutionReportArtifact.from_dict(read_json_file(path))
            if payload.scenario == scenario_name:
                history.append((payload, path))
        return history

    def load_brief_payload(self, execution_path: Path | None) -> dict | None:
        if execution_path is None:
            return None
        brief_path = execution_path.parent / "daily_brief.json"
        if not brief_path.exists():
            return None
        return read_json_file(brief_path)

    def load_brief_markdown(self, execution_path: Path | None) -> str | None:
        if execution_path is None:
            return None
        brief_path = execution_path.parent / "daily_brief.md"
        if not brief_path.exists():
            return None
        return brief_path.read_text(encoding="utf-8")

    def load_scheduler_status(self) -> SchedulerStatusArtifact | None:
        path = self.output_dir / "scheduler" / "scheduler_status.json"
        if not path.exists():
            return None
        return SchedulerStatusArtifact.from_dict(read_json_file(path))
