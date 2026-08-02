#!/usr/bin/env python3
"""SMS Bridge: Host-side service that exposes ModemManager SMS via HTTP.

Runs on the host, uses mmcli for modem communication.
Container calls localhost:9081 for SMS send/receive.

Usage:
    sudo python3 sms_bridge.py          # needs access to modem devices
    python3 sms_bridge.py --port 9081   # default port
"""

import argparse
import json
import logging
import re
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer

from mms_bridge import MMSInbox

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("sms_bridge")

MMCLI_COMMAND = ("sudo", "-n", "/usr/bin/mmcli")
MMS_INBOX = MMSInbox()


def run_mmcli(*args, timeout=10):
    """Run mmcli command and return stdout."""
    try:
        result = subprocess.run(
            [*MMCLI_COMMAND, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except FileNotFoundError:
        return "", "sudo or mmcli not found. Install ModemManager.", 1
    except subprocess.TimeoutExpired:
        return "", "mmcli timed out", 1


def find_modem_path():
    """Find the first usable modem object path."""
    out, err, rc = run_mmcli("-L")
    if rc != 0 or not out:
        return None
    # Output like: /org/freedesktop/ModemManager1/Modem/0 [QUALCOMM] SIMCOM...
    for line in out.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        path = line.split("[")[0].strip()
        if path.startswith("/org/"):
            return path
    return None


def find_modem_index():
    """Find the first modem index (0, 1, ...)."""
    path = find_modem_path()
    if path:
        return path.split("/")[-1]
    return "0"


def send_sms(modem_path: str, number: str, text: str):
    """Create and send an SMS via the installed mmcli API."""
    if not re.fullmatch(r"\+?[0-9]{7,15}", number):
        return False, "invalid destination number"

    idx = modem_path.rsplit("/", 1)[-1]
    # mmcli's GLib key/value parser is fragile around quotes and backslashes in
    # message bodies. Its file option preserves arbitrary UTF-8 text and keeps
    # the validated phone number separate from the body.
    with tempfile.NamedTemporaryFile("w", encoding="utf-8") as text_file:
        text_file.write(text)
        text_file.flush()
        out, err, rc = run_mmcli(
            "-m",
            idx,
            f"--messaging-create-sms=number='{number}'",
            f"--messaging-create-sms-with-text={text_file.name}",
        )
    if rc != 0:
        return False, err or out

    match = re.search(r"/org/freedesktop/ModemManager1/SMS/(\d+)", out)
    if not match:
        return False, f"SMS created but path was not returned: {out}"

    sms_idx = match.group(1)
    send_out, send_err, send_rc = run_mmcli("-s", sms_idx, "--send", timeout=30)
    if send_rc != 0:
        run_mmcli("-m", idx, "--messaging-delete-sms", sms_idx)
        return False, send_err or send_out

    run_mmcli("-m", idx, "--messaging-delete-sms", sms_idx)
    return True, send_out


def _parse_keyvalue(output: str) -> dict[str, str]:
    values = {}
    for line in output.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip()] = value.strip()
    return values


def get_inbox(modem_path: str):
    """Get inbound SMS messages currently stored by ModemManager."""
    idx = modem_path.rsplit("/", 1)[-1]
    out, err, rc = run_mmcli("-m", idx, "--messaging-list-sms")
    if rc != 0:
        return [], err or out

    messages = []
    msg_paths = re.findall(r"/org/freedesktop/ModemManager1/SMS/\d+", out)
    for msg_path in msg_paths:
        msg_idx = msg_path.rsplit("/", 1)[-1]
        detail, _, detail_rc = run_mmcli("-s", msg_idx, "-K")
        if detail_rc != 0:
            continue

        props = _parse_keyvalue(detail)
        pdu_type = props.get("sms.properties.pdu-type", "").lower()
        sender = props.get("sms.content.number", "")
        body = props.get("sms.content.text", "")
        if pdu_type == "deliver" and sender and body:
            messages.append({"sender": sender, "text": body, "path": msg_path})

    return messages, ""


def delete_message(modem_path: str, msg_path: str):
    """Delete a read SMS message."""
    idx = find_modem_index()
    msg_idx = msg_path.split("/")[-1]
    run_mmcli("-m", idx, "--messaging-delete-sms", msg_idx)


class SMSHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logger.info(format % args)

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        if self.path == "/health":
            modem_path = find_modem_path()
            self._send_json({"status": "ok", "modem": modem_path is not None})
        elif self.path == "/sms/inbox":
            modem_path = find_modem_path()
            if not modem_path:
                self._send_json({"error": "no modem found"}, 503)
                return
            messages, err = get_inbox(modem_path)
            # Delete read messages
            for msg in messages:
                delete_message(modem_path, msg["path"])
            self._send_json({"messages": messages})
        elif self.path == "/sms/modem":
            modem_path = find_modem_path()
            info, _, _ = run_mmcli("-m", modem_path.split("/")[-1]) if modem_path else ("", "", 1)
            self._send_json({"modem_path": modem_path, "info": info})
        elif self.path == "/mms/health":
            health = MMS_INBOX.health()
            self._send_json(health, 200 if health.get("mmsd") else 503)
        elif self.path == "/mms/inbox":
            try:
                self._send_json({"messages": MMS_INBOX.poll()})
            except Exception as exc:
                logger.exception("MMS inbox poll failed")
                self._send_json({"error": str(exc)}, 503)
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._send_json({"error": "invalid JSON"}, 400)
            return

        if self.path == "/mms/ack":
            message_id = str(data.get("id", ""))
            if MMS_INBOX.acknowledge(message_id):
                self._send_json({"status": "acknowledged", "id": message_id})
            else:
                self._send_json({"error": "unknown or invalid MMS id"}, 404)
            return

        if self.path != "/sms/send":
            self._send_json({"error": "not found"}, 404)
            return

        number = data.get("number", "")
        text = data.get("text", "")
        if not number or not text:
            self._send_json({"error": "number and text required"}, 400)
            return

        modem_path = find_modem_path()
        if not modem_path:
            self._send_json({"error": "no modem found"}, 503)
            return

        ok, result = send_sms(modem_path, number, text)
        if ok:
            self._send_json({"status": "sent", "result": result})
        else:
            logger.error("SMS send failed: %s", result)
            self._send_json({"error": result}, 500)


def main():
    parser = argparse.ArgumentParser(description="SMS Bridge for OpenPup")
    parser.add_argument("--port", type=int, default=9081, help="HTTP port (default: 9081)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address")
    args = parser.parse_args()

    # Verify mmcli works
    modem_path = find_modem_path()
    if modem_path:
        logger.info("Modem found: %s", modem_path)
    else:
        logger.warning("No modem found! SMS send/receive will fail.")
        logger.info("Check with: mmcli -L")

    server = HTTPServer((args.host, args.port), SMSHandler)
    logger.info("SMS Bridge listening on %s:%d", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
