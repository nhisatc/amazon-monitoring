"""
Send a one-off message to the alert recipients from the company address.

The monitors already send from SMTP_FROM_ADDRESS, but ad-hoc team messages had
no path to that identity — the only other option was a personal mailbox, which
is the wrong sender for anything company-facing. This closes that gap using the
same credentials the automated alerts use.

Usage:
    python send_announcement.py --subject "..." --body-file message.txt
    python send_announcement.py --subject "..." --body-file message.txt --dry-run
"""

import argparse
import os

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

from alerts import _recipients, _sender, send_email  # noqa: E402


def to_html(text: str) -> str:
    """Wrap plain text so it renders readably without mangling the wording."""
    escaped = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    return (
        "<html><body style='font-family:-apple-system,Segoe UI,Arial,sans-serif;"
        "font-size:14px;color:#222;max-width:760px;white-space:pre-wrap'>"
        f"{escaped}"
        "</body></html>"
    )


def main():
    parser = argparse.ArgumentParser(description="Send a team message from the company address")
    parser.add_argument("--subject", required=True)
    parser.add_argument("--body-file", required=True,
                        help="Path to a UTF-8 text file holding the message body")
    parser.add_argument("--to", default="",
                        help="Comma-separated override; defaults to ALERT_RECIPIENTS")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with open(args.body_file, encoding="utf-8") as f:
        body = f.read()

    recipients = ([r.strip() for r in args.to.split(",") if r.strip()]
                  if args.to else _recipients())
    from_address, smtp_user, _ = _sender()

    print("=== Announcement ===")
    print(f"  from      : {from_address}  (auth as {smtp_user})")
    print(f"  to        : {', '.join(recipients)}")
    print(f"  subject   : {args.subject}")
    print(f"  body      : {len(body)} chars")

    if from_address.lower().endswith("@gmail.com"):
        print("\n  REFUSING: sender resolves to a personal Gmail address.")
        print("  Set SMTP_FROM_ADDRESS / SMTP_FROM_PASSWORD so team mail comes")
        print("  from the company address, or pass --to for a personal note.")
        raise SystemExit(1)

    if args.dry_run:
        os.environ["ALERT_DRY_RUN"] = "1"

    ok = send_email(args.subject, to_html(body), recipients)
    print("  sent" if ok else "  FAILED")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
