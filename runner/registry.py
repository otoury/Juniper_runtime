import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


STATE_PATH = Path("data/runtime_services.json")
STATE_PATH.parent.mkdir(parents=True, exist_ok=True)


def now():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ServiceState:
    name: str
    cmd: list[str]
    pid: int | None
    status: str
    started_at: str | None
    exited_at: str | None = None
    exit_code: int | None = None
    restart_count: int = 0


def save_services(services):
    data = {}

    for service in services:
        p = service.process

        data[service.name] = asdict(ServiceState(
            name=service.name,
            cmd=service.cmd,
            pid=p.pid if p else None,
            status="running" if p and p.poll() is None else "exited",
            started_at=getattr(service, "started_at", None),
            exited_at=getattr(service, "exited_at", None),
            exit_code=p.poll() if p else None,
            restart_count=getattr(service, "restart_count", 0),
        ))

    STATE_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_services():
    if not STATE_PATH.exists():
        return {}

    return json.loads(
        STATE_PATH.read_text(encoding="utf-8")
    )