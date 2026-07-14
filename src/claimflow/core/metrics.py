"""In-process Prometheus metrics for claim processing observability."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class MetricsRegistry:
    """Thread-safe counters / timing stats exposed via ``GET /metrics``."""

    claims_submitted: int = 0
    claims_approved: int = 0
    claims_rejected: int = 0
    _processing_times: list[float] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_submission(self) -> None:
        with self._lock:
            self.claims_submitted += 1

    def record_outcome(self, status: str) -> None:
        """Increment approved/rejected counters from a final claim status."""
        normalized = status.upper()
        with self._lock:
            if normalized == "APPROVED":
                self.claims_approved += 1
            elif normalized == "REJECTED":
                self.claims_rejected += 1

    def record_processing_time(self, seconds: float) -> None:
        if seconds < 0:
            return
        with self._lock:
            self._processing_times.append(seconds)

    @property
    def avg_processing_time(self) -> float:
        with self._lock:
            if not self._processing_times:
                return 0.0
            return sum(self._processing_times) / len(self._processing_times)

    def snapshot(self) -> dict[str, float | int]:
        with self._lock:
            times = list(self._processing_times)
            submitted = self.claims_submitted
            approved = self.claims_approved
            rejected = self.claims_rejected
        avg = sum(times) / len(times) if times else 0.0
        return {
            "claims_submitted": submitted,
            "claims_approved": approved,
            "claims_rejected": rejected,
            "avg_processing_time": avg,
            "processing_samples": len(times),
        }

    def render_prometheus(self) -> str:
        """Return metrics in Prometheus text exposition format."""
        snap = self.snapshot()
        lines = [
            "# HELP claims_submitted Total claim submissions received.",
            "# TYPE claims_submitted counter",
            f"claims_submitted {snap['claims_submitted']}",
            "# HELP claims_approved Total claims auto- or manually approved.",
            "# TYPE claims_approved counter",
            f"claims_approved {snap['claims_approved']}",
            "# HELP claims_rejected Total claims auto- or manually rejected.",
            "# TYPE claims_rejected counter",
            f"claims_rejected {snap['claims_rejected']}",
            "# HELP avg_processing_time Average end-to-end claim processing time in seconds.",
            "# TYPE avg_processing_time gauge",
            f"avg_processing_time {snap['avg_processing_time']:.6f}",
            "",
        ]
        return "\n".join(lines)

    def reset(self) -> None:
        """Reset all metrics (test helper)."""
        with self._lock:
            self.claims_submitted = 0
            self.claims_approved = 0
            self.claims_rejected = 0
            self._processing_times.clear()


metrics = MetricsRegistry()
