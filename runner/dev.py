import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from runner.registry import now, save_services

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"

load_dotenv(ENV_PATH, override=True)


@dataclass
class RunningService:
    name: str
    cmd: list[str]
    process: subprocess.Popen | None = None
    reported_exit: bool = False
    started_at: str | None = None
    exited_at: str | None = None
    restart_count: int = 0
    max_restarts: int = 3

SERVICES = [
    RunningService(
        name="juniper_bot",
        cmd=[sys.executable, "-m", "gateway.juniper_bot"],
    ),
    RunningService(
        name="alexis_bot",
        cmd=[sys.executable, "-m", "gateway.alexis_bot"],
    ),
    RunningService(
        name="dashboard",
        cmd=[sys.executable, "-m", "runner.ui.dashboard"],
    ),
]


def start_service(service: RunningService):
    print(f"Starting {service.name}...")

    env = os.environ.copy()

    service.process = subprocess.Popen(
        service.cmd,
        cwd=ROOT,
        env=env,
    )

    service.started_at = now()
    service.exited_at = None
    service.reported_exit = False

    save_services(SERVICES)


def start_services():
    print(f"Loaded env from: {ENV_PATH}")

    for service in SERVICES:
        start_service(service)


def monitor_services():
    for service in SERVICES:
        p = service.process

        if p is None:
            continue

        code = p.poll()

        if code is None:
            continue

        if not service.reported_exit:
            print(f"{service.name} exited with code {code}")

            service.reported_exit = True
            service.exited_at = now()

            save_services(SERVICES)

        if service.restart_count >= service.max_restarts:
            continue

        print(
            f"Restarting {service.name} "
            f"({service.restart_count + 1}/{service.max_restarts})..."
        )

        service.restart_count += 1
        time.sleep(2)
        start_service(service)
        save_services(SERVICES)

def stop_services():
    print("\nStopping Juniper dev environment...")

    for service in SERVICES:
        p = service.process

        if p and p.poll() is None:
            print(f"Stopping {service.name}...")
            p.terminate()

    time.sleep(2)

    for service in SERVICES:
        p = service.process

        if p and p.poll() is None:
            print(f"Killing {service.name}...")
            p.kill()


def main():
    start_services()

    try:
        while True:
            monitor_services()
            save_services(SERVICES)
            time.sleep(2)

    except KeyboardInterrupt:
        stop_services()


if __name__ == "__main__":
    main()