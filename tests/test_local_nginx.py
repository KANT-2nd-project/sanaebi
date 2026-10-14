"""프로젝트 nginx의 종료 대상 식별을 검증한다."""

import sys
import unittest

if sys.platform == "linux":
    from scripts.local_nginx import owns_process


@unittest.skipUnless(sys.platform == "linux", "WSL/Linux 전용 실행 도구")
class ProcessOwnershipTests(unittest.TestCase):
    def test_reused_pid_is_not_ours(self):
        record = {"pid": 123, "start_time": "100", "uid": 1001}
        identity = {
            "pid": 123,
            "start_time": "200",
            "uid": 1001,
            "cmdline": "nginx: master process nginx -c /project/tmp/nginx/nginx.conf",
        }
        self.assertFalse(
            owns_process(record, identity, "/project/tmp/nginx/nginx.conf")
        )

    def test_only_same_master_instance_is_owned(self):
        config = "/project/tmp/nginx/nginx.conf"
        record = {"pid": 123, "start_time": "100", "uid": 1001}
        identity = {**record, "cmdline": f"nginx: master process nginx -c {config}"}
        self.assertTrue(owns_process(record, identity, config))
        for override in (
            {"uid": 0},
            {"pid": 124},
            {"start_time": "101"},
            {"cmdline": "sleep 600"},
            {"cmdline": f"nginx: master process nginx -c {config}.other"},
            {"cmdline": "nginx: worker process"},
        ):
            with self.subTest(override=override):
                self.assertFalse(owns_process(record, {**identity, **override}, config))
        self.assertFalse(owns_process(record, None, config))

    def test_busy_port_is_refused(self):
        import socket

        from scripts.local_nginx import ensure_port_available

        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            with self.assertRaisesRegex(RuntimeError, "사용 중"):
                ensure_port_available(listener.getsockname()[1])

    def test_stop_refuses_foreign_process_without_signalling(self):
        from unittest.mock import patch

        from scripts import local_nginx

        record = {"pid": 123, "start_time": "100", "uid": 1001}
        with (
            patch.object(local_nginx, "read_owner", return_value=record),
            patch.object(local_nginx.os, "pidfd_open", return_value=42),
            patch.object(local_nginx.os, "close"),
            patch.object(
                local_nginx,
                "process_identity",
                return_value={
                    **record,
                    "cmdline": "some other process",
                },
            ),
            patch.object(local_nginx.signal, "pidfd_send_signal") as send_signal,
        ):
            with self.assertRaisesRegex(RuntimeError, "종료를 거부"):
                local_nginx.stop()
            send_signal.assert_not_called()
