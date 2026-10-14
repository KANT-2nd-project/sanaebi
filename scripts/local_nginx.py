"""WSL/Linux에서 시스템 서비스와 분리한 프로젝트 nginx를 관리합니다."""

import argparse
import fcntl
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "tmp" / "nginx"
CONFIG = RUNTIME / "nginx.conf"
OWNER = RUNTIME / "owner.json"


def owns_process(record, identity, config_path):
    if not identity:
        return False
    return (
        all(
            record.get(key) == identity.get(key) for key in ("pid", "start_time", "uid")
        )
        and identity["cmdline"].startswith("nginx: master process ")
        and identity["cmdline"].strip().endswith(f"-c {config_path}")
    )


def process_identity(pid):
    try:
        proc = Path("/proc") / str(pid)
        fields = (proc / "stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            return None
        return {
            "pid": pid,
            "start_time": fields[19],
            "uid": proc.stat().st_uid,
            "cmdline": (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(),
        }
    except FileNotFoundError:
        return None


def port_number(value):
    port = int(value)
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError("포트는 1024~65535여야 합니다.")
    return port


def ensure_port_available(port):
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError as error:
            raise RuntimeError(
                f"127.0.0.1:{port}가 사용 중입니다. 종료하지 않습니다."
            ) from error


def render_config(port, upstream_port):
    out = ROOT / "web" / "out"
    for name in ("index.html", "404.html", "_next"):
        if not (out / name).exists():
            raise RuntimeError(
                "정적 산출물이 없습니다. web에서 npm run build를 실행하세요."
            )
    if not Path("/etc/nginx/mime.types").is_file():
        raise RuntimeError(
            "/etc/nginx/mime.types가 없습니다. WSL nginx 설치를 확인하세요."
        )
    path = str(out)
    if any(char in path for char in ("$", "\n", "\r")):
        raise RuntimeError("nginx 경로에는 $, 개행 문자를 사용할 수 없습니다.")
    path = path.replace("\\", "\\\\").replace('"', '\\"')
    return (
        (ROOT / "deployment" / "nginx.conf")
        .read_text()
        .replace("@@OUT_DIR@@", path)
        .replace("@@PORT@@", str(port))
        .replace("@@UPSTREAM_PORT@@", str(upstream_port))
    )


def read_owner():
    if not OWNER.exists():
        return None
    try:
        record = json.loads(OWNER.read_text())
        if not isinstance(record.get("pid"), int) or record["pid"] <= 1:
            raise ValueError("invalid pid")
        if record.get("uid") != os.getuid():
            raise ValueError("different uid")
        return record
    except (ValueError, TypeError, AttributeError) as error:
        raise RuntimeError(
            "프로젝트 PID 기록이 잘못됐습니다. 프로세스를 종료하지 않습니다."
        ) from error


def stop():
    record = read_owner()
    if not record:
        print("관리 중인 프로젝트 nginx가 없습니다.")
        return
    try:
        # pidfd로 PID 재사용 경합 중에도 다른 프로세스에 신호를 보내지 않습니다.
        descriptor = os.pidfd_open(record["pid"])
    except ProcessLookupError:
        OWNER.unlink()
        print("프로젝트 nginx는 이미 종료됐습니다.")
        return
    try:
        identity = process_identity(record["pid"])
        if identity is None:
            OWNER.unlink()
            print("프로젝트 nginx는 이미 종료됐습니다.")
            return
        if not owns_process(record, identity, str(CONFIG)):
            raise RuntimeError(
                "PID의 소유·시작 시각·설정이 일치하지 않아 종료를 거부합니다."
            )
        signal.pidfd_send_signal(descriptor, signal.SIGQUIT)
        for _ in range(80):
            if process_identity(record["pid"]) is None:
                OWNER.unlink(missing_ok=True)
                print("프로젝트 nginx를 종료했습니다.")
                return
            time.sleep(0.1)
        raise RuntimeError(
            "정상 종료를 기다리는 중입니다. 다른 프로세스를 강제 종료하지 않습니다."
        )
    finally:
        os.close(descriptor)


def run(command, port, upstream_port):
    binary = shutil.which("nginx") or "/usr/sbin/nginx"
    if not Path(binary).is_file():
        raise RuntimeError(
            "nginx가 없습니다. sudo apt-get install nginx를 먼저 실행하세요."
        )
    record = read_owner()
    if command == "start" and record and process_identity(record["pid"]):
        raise RuntimeError(
            "프로젝트 PID가 실행 중입니다. stop으로 종료한 뒤 시작하세요."
        )
    rendered = render_config(port, upstream_port)
    check_config = RUNTIME / "check.conf"
    check_config.write_text(rendered)
    prefix = str(RUNTIME) + "/"
    subprocess.run([binary, "-p", prefix, "-c", str(check_config), "-t"], check=True)
    if command == "check":
        print("설정·빌드 산출물 확인 완료. 실행 중인 설정은 변경하지 않았습니다.")
        return
    ensure_port_available(port)
    CONFIG.write_text(rendered)
    with (RUNTIME / "launcher.log").open("ab") as log:
        process = subprocess.Popen(
            [binary, "-p", prefix, "-c", str(CONFIG)],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    for _ in range(50):
        if process.poll() is not None:
            raise RuntimeError("nginx 시작 실패: tmp/nginx/launcher.log를 확인하세요.")
        identity = process_identity(process.pid)
        if identity and identity["cmdline"].startswith("nginx: master process "):
            OWNER.write_text(json.dumps(identity, ensure_ascii=False) + "\n")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    print(
                        f"http://127.0.0.1:{port} (upstream 127.0.0.1:{upstream_port})"
                    )
                    return
            except OSError:
                pass
        time.sleep(0.1)
    # Popen으로 직접 생성한 프로세스만 정리합니다.
    process.terminate()
    process.wait(timeout=8)
    raise RuntimeError("nginx가 제한 시간 내에 준비되지 않았습니다.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "start", "stop"))
    parser.add_argument("--port", type=port_number, default=8080)
    parser.add_argument("--upstream-port", type=port_number, default=8000)
    args = parser.parse_args()
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with (RUNTIME / "control.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if args.command == "stop":
                stop()
            else:
                run(args.command, args.port, args.upstream_port)
        except (RuntimeError, OSError, subprocess.SubprocessError) as error:
            print(f"오류: {error}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
