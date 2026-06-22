#!/usr/bin/env python3
"""Send a generated briefing through QQ Mail SMTP."""

from __future__ import annotations

import argparse
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path


SMTP_HOST = "smtp.qq.com"
SMTP_PORT = 465
REQUIRED_ENV = ("SMTP_USERNAME", "SMTP_PASSWORD", "MAIL_TO")


def parse_recipients(raw: str) -> list[str]:
    return [address.strip() for address in raw.split(",") if address.strip()]


def build_message(report: str, sender: str, recipients: list[str]) -> EmailMessage:
    first_line = report.splitlines()[0].removeprefix("# ").strip()
    subject = first_line or "每日资讯简报"
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(report)
    return message


def send_report(report_path: Path) -> bool:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        print(
            "Email skipped because GitHub Secrets are not configured: "
            + ", ".join(missing)
        )
        return False

    sender = os.environ["SMTP_USERNAME"].strip()
    password = os.environ["SMTP_PASSWORD"].strip()
    recipients = parse_recipients(os.environ["MAIL_TO"])
    if not recipients:
        raise ValueError("MAIL_TO does not contain a valid recipient")

    report = report_path.read_text(encoding="utf-8")
    message = build_message(report, sender, recipients)
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
        smtp.login(sender, password)
        smtp.send_message(message, from_addr=sender, to_addrs=recipients)

    print(f"Email sent to {len(recipients)} recipient(s).")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=Path("report.md"))
    args = parser.parse_args()
    send_report(args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
