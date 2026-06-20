"""Email service for purchase-order notifications.

Uses the standard library (``smtplib`` + ``email.message``) and runs the blocking
send on a worker thread so it never blocks the event loop. When SMTP is not
enabled/configured, sends are skipped gracefully (logged, returns ``sent=False``)
rather than raising — so the API still succeeds in environments without mail.
"""
from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from app.core.logging import get_logger

logger = get_logger(__name__)


class EmailService:
    def __init__(
        self,
        *,
        enabled: bool,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        use_tls: bool,
        from_addr: str,
    ) -> None:
        self.enabled = enabled
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.from_addr = from_addr

    @classmethod
    def from_settings(cls) -> "EmailService":
        from app.core.config import settings

        return cls(
            enabled=settings.smtp_enabled,
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            use_tls=settings.smtp_use_tls,
            from_addr=settings.smtp_from,
        )

    # ----------------------------- core ------------------------------ #
    def _send_sync(self, msg: EmailMessage) -> None:
        with smtplib.SMTP(self.host, self.port, timeout=20) as server:
            if self.use_tls:
                server.starttls()
            if self.username:
                server.login(self.username, self.password or "")
            server.send_message(msg)

    async def send(
        self,
        *,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        attachment: bytes | None = None,
        attachment_name: str = "document.pdf",
    ) -> tuple[bool, str]:
        recipients = [r for r in (to or []) if r]
        if not recipients:
            return False, "no recipient address available"
        if not self.enabled:
            logger.info("email_skipped", reason="smtp_disabled", subject=subject, to=recipients)
            return False, "email disabled (SMTP not enabled)"

        msg = EmailMessage()
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(recipients)
        if cc:
            msg["Cc"] = ", ".join(cc)
        msg["Subject"] = subject
        msg.set_content(body)
        if attachment is not None:
            msg.add_attachment(
                attachment, maintype="application", subtype="pdf", filename=attachment_name
            )

        try:
            await asyncio.to_thread(self._send_sync, msg)
            logger.info("email_sent", subject=subject, to=recipients)
            return True, "sent"
        except Exception as exc:  # noqa: BLE001 - never fail the request on mail errors
            logger.warning("email_failed", subject=subject, error=str(exc))
            return False, f"send failed: {exc}"

    # ------------------------- templated sends ------------------------ #
    async def send_purchase_order(
        self, *, to: list[str], po_number: str, pdf_bytes: bytes, cc: list[str] | None = None
    ) -> tuple[bool, str]:
        body = (
            f"Please find attached purchase order {po_number}.\n\n"
            "Kindly confirm receipt and the expected delivery date.\n"
        )
        return await self.send(
            to=to,
            cc=cc,
            subject=f"Purchase Order {po_number}",
            body=body,
            attachment=pdf_bytes,
            attachment_name=f"{po_number}.pdf",
        )

    async def send_approval_notification(
        self,
        *,
        to: list[str],
        po_number: str,
        approved: bool,
        comment: str | None = None,
        cc: list[str] | None = None,
    ) -> tuple[bool, str]:
        outcome = "approved" if approved else "rejected"
        body = f"Purchase order {po_number} has been {outcome}."
        if comment:
            body += f"\n\nComment: {comment}"
        return await self.send(
            to=to, cc=cc, subject=f"Purchase Order {po_number} {outcome}", body=body
        )

    async def send_receipt_notification(
        self,
        *,
        to: list[str],
        po_number: str,
        fully_received: bool,
        cc: list[str] | None = None,
    ) -> tuple[bool, str]:
        state = "fully received" if fully_received else "partially received"
        body = f"Goods for purchase order {po_number} have been {state}."
        return await self.send(
            to=to, cc=cc, subject=f"Purchase Order {po_number} - goods {state}", body=body
        )
