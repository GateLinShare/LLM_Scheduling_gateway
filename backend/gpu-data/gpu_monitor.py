#!/usr/bin/env python3
import subprocess
import json
import sys
from typing import Any
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import paramiko
except ImportError:
    paramiko = None


def get_local_gpu_info() -> list[dict[str, Any]]:
    """Get GPU info on local machine."""
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,name,memory.total,memory.used,memory.free",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, check=True
    )
    return _parse_gpu_output(result.stdout)


def _parse_gpu_output(output: str) -> list[dict[str, Any]]:
    """Parse nvidia-smi CSV output."""
    gpus = []
    for line in output.strip().split("\n"):
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        index, name, total, used, free = parts
        total_mb = int(total)
        used_mb = int(used)
        used_pct = round(used_mb / total_mb * 100, 1) if total_mb > 0 else 0.0
        gpus.append({
            "index": int(index),
            "model": name,
            "memory_total_mb": total_mb,
            "memory_used_mb": used_mb,
            "memory_free_mb": int(free),
            "memory_used_percent": used_pct
        })
    return gpus


def get_remote_gpu_info(ip: str, username: str, password: str, timeout: int = 10) -> list[dict[str, Any]]:
    """SSH to remote server and get GPU info via paramiko."""
    if paramiko is None:
        raise ImportError("paramiko not installed, run: pip install paramiko")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(ip, username=username, password=password, timeout=timeout, look_for_keys=False, allow_agent=False)
    except Exception as e:
        raise RuntimeError(f"SSH connect failed to {ip}: {e}")

    try:
        stdin, stdout, stderr = ssh.exec_command(
            "nvidia-smi --query-gpu=index,name,memory.total,memory.used,memory.free --format=csv,noheader,nounits",
            timeout=30
        )
        output = stdout.read().decode("utf-8")
        err = stderr.read().decode("utf-8")
        if err and not output:
            raise RuntimeError(f"nvidia-smi error: {err.strip()}")
        return _parse_gpu_output(output)
    finally:
        ssh.close()


def fetch_server_gpus(server: dict) -> tuple[str, list | str]:
    """Fetch GPUs from a single server. Returns (ip, gpus_or_error)."""
    ip = server["ip"]
    try:
        gpus = get_remote_gpu_info(ip, server["username"], server["password"])
        return (ip, gpus)
    except Exception as e:
        return (ip, str(e))


def get_all_gpu_info(config_path: str = "servers.json", include_local: bool = True) -> dict[str, Any]:
    """Get GPU info from all servers in config, parallel execution."""
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    result: dict[str, Any] = {"servers": {}}

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(fetch_server_gpus, s): s["ip"] for s in config["servers"]}
        for future in as_completed(futures):
            ip, data = future.result()
            result["servers"][ip] = data

    if include_local:
        try:
            local_gpus = get_local_gpu_info()
            result["servers"]["local"] = local_gpus
        except Exception as e:
            result["servers"]["local"] = str(e)

    return result


def save_all_gpu_info(filepath: str = "all_gpu_info.json", config_path: str = "servers.json") -> None:
    """Save GPU info from all servers to JSON file."""
    info = get_all_gpu_info(config_path)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2, ensure_ascii=False)
    print(f"Saved to {filepath}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="GPU Monitor")
    parser.add_argument("--config", default="servers.json", help="Server config file")
    parser.add_argument("--save", help="Save output to file")
    parser.add_argument("--no-local", action="store_true", help="Skip local GPU")
    args = parser.parse_args()

    info = get_all_gpu_info(args.config, include_local=not args.no_local)
    print(json.dumps(info, indent=2, ensure_ascii=False))

    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2, ensure_ascii=False)
        print(f"\nSaved to {args.save}")
