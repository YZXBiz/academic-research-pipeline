"""TCP command server for experiment container.

Listens on port 8000, executes shell commands, streams output as JSON.
Adapted from AI-Researcher (HKUDS).
"""
import argparse
import json
import socket
import subprocess


def receive_all(conn, buffer_size=4096):
    data = b""
    while True:
        part = conn.recv(buffer_size)
        data += part
        if len(part) < buffer_size:
            break
    return data.decode()


def main(port, workplace):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", port))
    server.listen(1)
    print(f"[tcp_server] Listening on port {port}, workplace={workplace}")

    while True:
        conn, addr = server.accept()
        print(f"[tcp_server] Connection from {addr}")
        try:
            while True:
                command = receive_all(conn)
                if not command:
                    break
                try:
                    process = subprocess.Popen(
                        ["/bin/bash", "-c", command],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        cwd=workplace,
                    )
                    output = ""
                    for line in iter(process.stdout.readline, ""):
                        output += line
                        chunk = {"type": "chunk", "data": line}
                        conn.sendall(json.dumps(chunk).encode() + b"\n")
                    process.wait()
                    final = {
                        "type": "final",
                        "status": process.returncode,
                        "result": output,
                    }
                    conn.sendall(json.dumps(final).encode() + b"\n")
                except Exception as e:
                    error = {"type": "final", "status": -1, "result": f"Error: {e}"}
                    conn.sendall(json.dumps(error).encode() + b"\n")
        finally:
            conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--workplace", type=str, default="/workspace")
    args = parser.parse_args()
    main(args.port, args.workplace)
