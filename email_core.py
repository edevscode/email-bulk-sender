import logging
import mimetypes
import re
import smtplib
import threading
import time
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

GMAIL_SMTP_SERVER = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587
DEFAULT_SEND_DELAY = 3
DEFAULT_MAX_EMAILS = 150
EMAIL_VALIDATION_REGEX = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
EMAIL_COLUMN_HINTS = ["email", "emails", "e-mail", "employer_email", "recipient_email"]
PERSONALIZATION_COLUMNS = ["name", "first_name", "last_name", "company", "organization"]
ALLOWED_ATTACHMENT_TYPES = ["pdf", "docx", "doc", "txt", "png", "jpg", "jpeg", "xlsx"]


logger = logging.getLogger(__name__)


def validate_email(email: str) -> bool:
    return re.match(EMAIL_VALIDATION_REGEX, email.strip()) is not None


def detect_email_column(df: pd.DataFrame) -> Optional[str]:
    columns_lower = [str(col).lower().strip() for col in df.columns]
    for hint in EMAIL_COLUMN_HINTS:
        if hint in columns_lower:
            original_idx = columns_lower.index(hint)
            return str(df.columns[original_idx])
    return None


def get_personalization_columns(df: pd.DataFrame) -> List[str]:
    columns_lower = {str(col).lower(): str(col) for col in df.columns}
    available: List[str] = []
    for hint in PERSONALIZATION_COLUMNS:
        if hint in columns_lower:
            available.append(columns_lower[hint])
    return available


def replace_template_variables(text: str, row_data: Dict[str, str]) -> str:
    result = text
    for key, value in row_data.items():
        placeholder = f"{{{{{key}}}}}"
        result = result.replace(placeholder, str(value) if value else "")
    return result


def deduplicate_emails(df: pd.DataFrame, email_column: str) -> pd.DataFrame:
    return df.drop_duplicates(subset=[email_column], keep="first")


def prepare_attachments_from_uploads(uploaded_files: List[Tuple[str, bytes]]) -> List[Tuple[str, bytes, str]]:
    attachments: List[Tuple[str, bytes, str]] = []
    for filename, content in uploaded_files or []:
        file_ext = Path(filename).suffix.lstrip(".").lower()
        if file_ext not in ALLOWED_ATTACHMENT_TYPES:
            continue
        mime_type, _ = mimetypes.guess_type(filename)
        if not mime_type:
            mime_type = "application/octet-stream"
        attachments.append((filename, content, mime_type))
    return attachments


def build_email_message(
    from_email: str,
    to_email: str,
    subject: str,
    body: str,
    attachments: List[Tuple[str, bytes, str]],
    is_html: bool = False,
    signature: str = "",
) -> MIMEMultipart:
    msg = MIMEMultipart("related")
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)

    full_body = body
    if signature:
        full_body = f"{body}\n\n{signature}"

    if is_html:
        msg.attach(MIMEText(full_body, "html"))
    else:
        msg.attach(MIMEText(full_body, "plain"))

    for filename, content, mime_type in attachments:
        maintype, subtype = mime_type.split("/", 1) if "/" in mime_type else (mime_type, "")
        attachment = MIMEBase(maintype, subtype)
        attachment.set_payload(content)
        encoders.encode_base64(attachment)
        attachment.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(attachment)

    return msg


def send_email_smtp(
    from_email: str,
    app_password: str,
    to_email: str,
    message: MIMEMultipart,
) -> Tuple[bool, str]:
    try:
        server = smtplib.SMTP(GMAIL_SMTP_SERVER, GMAIL_SMTP_PORT)
        server.starttls()
        server.login(from_email, app_password)
        server.send_message(message)
        server.quit()
        return True, ""
    except smtplib.SMTPAuthenticationError:
        return False, "Authentication failed. Check email/app password."
    except smtplib.SMTPException as e:
        return False, f"SMTP error: {str(e)[:100]}"
    except Exception as e:
        return False, f"Error: {str(e)[:100]}"


def iter_send_all_emails(
    *,
    from_email: str,
    app_password: str,
    df: pd.DataFrame,
    email_column: str,
    recipients: List[str],
    subject: str,
    body: str,
    attachments: List[Tuple[str, bytes, str]],
    send_delay: int,
    enable_personalize: bool,
    personalization_columns: List[str],
    is_html: bool,
    signature: str,
    enable_dedup: bool,
    cancel_event: Optional[threading.Event] = None,
) -> Iterable[Dict[str, object]]:
    df_send = df.copy()

    if enable_dedup:
        df_send = deduplicate_emails(df_send, email_column)

    df_send[email_column] = df_send[email_column].astype(str)
    df_send = df_send[df_send[email_column].isin(set(recipients))].copy()

    df_send["valid_email"] = df_send[email_column].apply(validate_email)

    total = len(df_send)
    yield {"type": "info", "message": f"Sending {total} emails with {send_delay}s delay...", "progress": 0.0}

    results: List[Dict[str, str]] = []
    for i, (_, row) in enumerate(df_send.iterrows()):
        email = str(row[email_column])
        row_num = i + 1

        if cancel_event is not None and cancel_event.is_set():
            yield {
                "type": "done",
                "results": results,
                "progress": (row_num - 1) / max(1, total),
                "cancelled": True,
            }
            return

        if not row["valid_email"]:
            result = {"email": email, "status": "Invalid Email", "error_message": "Invalid email format"}
            results.append(result)
            yield {"type": "log", "level": "info", "message": f"[{row_num}] Invalid: {email}", "progress": (row_num / max(1, total))}
            continue

        row_data: Dict[str, str] = {"email": email}
        if enable_personalize:
            for col in personalization_columns:
                if col in df_send.columns:
                    row_data[col] = "" if pd.isna(row.get(col)) else str(row.get(col))

        personalized_body = replace_template_variables(body, row_data)

        try:
            msg = build_email_message(
                from_email=from_email,
                to_email=email,
                subject=subject,
                body=personalized_body,
                attachments=attachments,
                is_html=is_html,
                signature=signature,
            )
            success, error_msg = send_email_smtp(
                from_email=from_email,
                app_password=app_password,
                to_email=email,
                message=msg,
            )

            if success:
                result = {"email": email, "status": "Sent", "error_message": ""}
                results.append(result)
                yield {
                    "type": "log",
                    "level": "info",
                    "message": f"[{row_num}/{total}] Sent to {email}",
                    "progress": (row_num / max(1, total)),
                }
            else:
                result = {"email": email, "status": "Failed", "error_message": error_msg}
                results.append(result)
                yield {
                    "type": "log",
                    "level": "warning",
                    "message": f"[{row_num}/{total}] Failed: {email} - {error_msg}",
                    "progress": (row_num / max(1, total)),
                }

        except Exception as e:
            error_msg = f"Exception: {str(e)[:100]}"
            result = {"email": email, "status": "Failed", "error_message": error_msg}
            results.append(result)
            yield {
                "type": "log",
                "level": "error",
                "message": f"[{row_num}/{total}] Error: {email} - {error_msg}",
                "progress": (row_num / max(1, total)),
            }

        if row_num < total:
            remaining = float(send_delay)
            while remaining > 0:
                if cancel_event is not None and cancel_event.is_set():
                    yield {
                        "type": "done",
                        "results": results,
                        "progress": row_num / max(1, total),
                        "cancelled": True,
                    }
                    return
                step = 0.2 if remaining > 0.2 else remaining
                time.sleep(step)
                remaining -= step

    yield {"type": "done", "results": results, "progress": 1.0}
