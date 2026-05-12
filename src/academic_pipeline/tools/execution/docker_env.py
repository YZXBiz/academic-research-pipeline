"""Docker container environment with TCP communication."""
from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DOCKER_IMAGE = "academic-pipeline-sandbox:latest"


@dataclass
class DockerConfig:
    container_name: str = "experiment-sandbox"
    workplace_name: str = "workspace"
    communication_port: int = 0
    local_root: str = field(default_factory=os.getcwd)


class DockerEnv:
    """Manages a persistent Docker container with TCP command execution."""

    def __init__(self, config: DockerConfig) -> None:
        self.container_name = config.container_name
        self.workplace_name = config.workplace_name
        self.local_workplace = os.path.join(config.local_root, config.workplace_name)
        self.docker_workplace = f"/{config.workplace_name}"
        self.communication_port = config.communication_port or _find_free_port()

    def init_container(self) -> None:
        """Start Docker container with TCP server and volume mount."""
        os.makedirs(self.local_workplace, exist_ok=True)

        existing = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name={self.container_name}", "--format", "{{.Names}}"],
            capture_output=True, text=True,
        )
        if existing.stdout.strip() == self.container_name:
            running = subprocess.run(
                ["docker", "ps", "--filter", f"name={self.container_name}", "--format", "{{.Names}}"],
                capture_output=True, text=True,
            )
            if running.stdout.strip() == self.container_name:
                logger.info("Container '%s' already running", self.container_name)
                return
            subprocess.run(["docker", "start", self.container_name], check=True)
            logger.info("Container '%s' restarted", self.container_name)
        else:
            cmd = [
                "docker", "run", "-d",
                "--name", self.container_name,
                "-v", f"{self.local_workplace}:{self.docker_workplace}",
                "-w", self.docker_workplace,
                "-p", f"{self.communication_port}:8000",
                "--restart", "unless-stopped",
                DOCKER_IMAGE,
                "python", "/usr/local/bin/tcp_server.py",
                "--port", "8000",
                "--workplace", self.docker_workplace,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"Failed to start container: {result.stderr}")
            logger.info("Container '%s' started on port %d", self.container_name, self.communication_port)

        self._wait_for_ready()

    def _wait_for_ready(self, timeout: int = 60) -> None:
        """Wait until the TCP server inside the container is responding."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                result = self.run_command("echo ready")
                if result["status"] == 0:
                    return
            except (ConnectionRefusedError, OSError):
                pass
            time.sleep(1)
        raise TimeoutError(f"Container {self.container_name} not ready after {timeout}s")

    def run_command(self, command: str, stream_callback: object = None) -> dict:
        """Send command via TCP, stream output, return {status, result}."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect(("localhost", self.communication_port))
            s.sendall(command.encode())
            s.shutdown(socket.SHUT_WR)

            partial = ""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data = partial + chunk.decode("utf-8", errors="replace")
                lines = data.split("\n")
                for line in lines[:-1]:
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                        if msg["type"] == "chunk" and stream_callback:
                            stream_callback(msg["data"])
                        elif msg["type"] == "final":
                            return {"status": msg["status"], "result": msg["result"]}
                    except json.JSONDecodeError:
                        pass
                partial = lines[-1]

        return {"status": -1, "result": "Connection closed without response"}

    def stop_container(self) -> None:
        """Stop and remove the container."""
        subprocess.run(["docker", "stop", self.container_name], capture_output=True)
        subprocess.run(["docker", "rm", self.container_name], capture_output=True)
        logger.info("Container '%s' stopped and removed", self.container_name)


def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]
