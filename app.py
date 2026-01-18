"""
Bulk Email Sender - Production-Safe App
Streamlit UI for sending templated emails to multiple recipients via Gmail SMTP.
Uses App Password for authentication (OAuth module structure provided as notes).
"""

import streamlit as st
import pandas as pd
import smtplib
import time
import re
import mimetypes
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.utils import formatdate
from email import encoders
from pathlib import Path
from typing import Dict, List, Tuple
import logging

# ============================================================================
# CONFIGURATION & CONSTANTS
# ============================================================================

GMAIL_SMTP_SERVER = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587
DEFAULT_SEND_DELAY = 3  # seconds between emails
DEFAULT_MAX_EMAILS = 150
EMAIL_VALIDATION_REGEX = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
EMAIL_COLUMN_HINTS = ["email", "emails", "e-mail", "employer_email", "recipient_email"]
PERSONALIZATION_COLUMNS = ["name", "first_name", "last_name", "company", "organization"]
ALLOWED_ATTACHMENT_TYPES = ["pdf", "docx", "doc", "txt", "png", "jpg", "jpeg", "xlsx"]

# ============================================================================
# LOGGING & UTILITIES
# ============================================================================

def setup_logging():
    """Configure logging for email operations."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )
    return logging.getLogger(__name__)

logger = setup_logging()

def validate_email(email: str) -> bool:
    """Validate email format using regex."""
    return re.match(EMAIL_VALIDATION_REGEX, email.strip()) is not None

def detect_email_column(df: pd.DataFrame) -> str:
    """
    Auto-detect email column by searching for common headers.
    Returns column name if found, else None.
    """
    columns_lower = [col.lower().strip() for col in df.columns]
    for hint in EMAIL_COLUMN_HINTS:
        if hint in columns_lower:
            original_idx = columns_lower.index(hint)
            return df.columns[original_idx]
    return None

def get_personalization_columns(df: pd.DataFrame) -> List[str]:
    """
    Identify available personalization columns in the dataframe.
    Returns list of column names that match personalization hints.
    """
    columns_lower = {col.lower(): col for col in df.columns}
    available = []
    for hint in PERSONALIZATION_COLUMNS:
        if hint in columns_lower:
            available.append(columns_lower[hint])
    return available

def replace_template_variables(text: str, row_data: Dict[str, str]) -> str:
    """
    Replace template variables in text with values from row_data.
    Variables format: {{variable_name}}
    If variable not found in row_data, replace with empty string.
    """
    result = text
    for key, value in row_data.items():
        placeholder = f"{{{{{key}}}}}"
        result = result.replace(placeholder, str(value) if value else "")
    return result

def deduplicate_emails(df: pd.DataFrame, email_column: str) -> pd.DataFrame:
    """Remove duplicate email addresses, keeping first occurrence."""
    return df.drop_duplicates(subset=[email_column], keep="first")

def prepare_attachments(uploaded_files: List) -> List[Tuple[str, bytes, str]]:
    """
    Prepare attachment list with (filename, content, mimetype).
    Filters by allowed file types.
    """
    attachments = []
    if uploaded_files:
        for file in uploaded_files:
            file_ext = Path(file.name).suffix.lstrip(".").lower()
            if file_ext in ALLOWED_ATTACHMENT_TYPES:
                mime_type, _ = mimetypes.guess_type(file.name)
                if not mime_type:
                    mime_type = "application/octet-stream"
                attachments.append((file.name, file.read(), mime_type))
            else:
                st.warning(f"Skipping {file.name}: file type '{file_ext}' not allowed.")
    return attachments

def build_email_message(
    from_email: str,
    to_email: str,
    subject: str,
    body: str,
    attachments: List[Tuple[str, bytes, str]],
    is_html: bool = False,
    signature: str = ""
) -> MIMEMultipart:
    """
    Build a MIME multipart email message with attachments.
    """
    msg = MIMEMultipart("related")
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)

    # Prepare body with optional signature
    full_body = body
    if signature:
        full_body = f"{body}\n\n{signature}"

    # Attach body
    if is_html:
        msg.attach(MIMEText(full_body, "html"))
    else:
        msg.attach(MIMEText(full_body, "plain"))

    # Attach files
    for filename, content, mime_type in attachments:
        maintype, subtype = mime_type.split("/", 1) if "/" in mime_type else (mime_type, "")
        attachment = MIMEBase(maintype, subtype)
        attachment.set_payload(content)
        encoders.encode_base64(attachment)
        attachment.add_header(
            "Content-Disposition",
            "attachment",
            filename=filename
        )
        msg.attach(attachment)

    return msg

def send_email_smtp(
    from_email: str,
    app_password: str,
    to_email: str,
    message: MIMEMultipart
) -> Tuple[bool, str]:
    """
    Send email via Gmail SMTP.
    Returns (success: bool, error_message: str or "")
    """
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

# ============================================================================
# STREAMLIT APP
# ============================================================================

def main():
    st.set_page_config(
        page_title="Bulk Email Sender",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    st.title("Bulk Email Sender")
    st.markdown("Send personalized emails to multiple recipients safely with one click.")

    # Initialize session state
    if "send_results" not in st.session_state:
        st.session_state.send_results = None
    if "preview_data" not in st.session_state:
        st.session_state.preview_data = None

    # ========================================================================
    # SIDEBAR: GMAIL CREDENTIALS
    # ========================================================================
    with st.sidebar:
        st.header("Gmail Configuration")
        st.info(
            "**App Password Required:**\n"
            "1. Go to [myaccount.google.com/security](https://myaccount.google.com/security)\n"
            "2. Enable 2-Step Verification if needed\n"
            "3. Generate App Password (select Mail, Windows/Mac/Linux)\n"
            "4. Copy the 16-character password below"
        )
        from_email = st.text_input(
            "Your Gmail Address",
            placeholder="your.email@gmail.com",
            help="The sender's Gmail address"
        )
        app_password = st.text_input(
            "App Password",
            type="password",
            placeholder="16-character password",
            help="Never share this. It stays in memory only."
        )

        st.divider()
        st.header("Email Settings")
        send_delay = st.slider(
            "Delay between emails (seconds)",
            min_value=1,
            max_value=10,
            value=DEFAULT_SEND_DELAY,
            help="Higher delays reduce spam flagging"
        )
        max_emails = st.number_input(
            "Maximum emails per run",
            min_value=10,
            max_value=1000,
            value=DEFAULT_MAX_EMAILS,
            help="Safety limit to prevent accidents"
        )
        enable_dedup = st.checkbox(
            "Deduplicate emails",
            value=True,
            help="Remove duplicate email addresses"
        )

        st.divider()
        st.header("Email Format")
        is_html = st.checkbox(
            "Send as HTML",
            value=False,
            help="Enable for styled emails; disable for plain text"
        )
        signature = st.text_area(
            "Optional Signature",
            placeholder="Best regards,\nYour Name",
            help="Appended to every email",
            height=80
        )

    # ========================================================================
    # MAIN CONTENT: EMAIL COMPOSITION
    # ========================================================================
    col1, col2 = st.columns([1, 1])

    with col1:
        st.header("Compose Email")
        subject = st.text_input(
            "Subject",
            placeholder="e.g., Join Our Team - Opportunity",
            help="Subject line for all emails"
        )

    with col2:
        st.header("Attachments & Data")
        attachment_files = st.file_uploader(
            "Attach Files",
            type=ALLOWED_ATTACHMENT_TYPES,
            accept_multiple_files=True,
            help="PDF, DOCX, images, etc."
        )

    email_body = st.text_area(
        "Email Body",
        placeholder="Dear {{name}},\n\nWe are excited to connect with {{company}}...",
        height=200,
        help="Use {{variable}} for personalization (e.g., {{name}}, {{company}})"
    )

    st.info(
        "**Template Variables:** You can use `{{name}}`, `{{first_name}}`, "
        "`{{company}}`, `{{email}}` if those columns exist in your Excel file."
    )

    # ========================================================================
    # EXCEL UPLOAD & PREVIEW
    # ========================================================================
    st.header("Recipients (Excel)")
    excel_file = st.file_uploader(
        "Upload Excel File (.xlsx)",
        type=["xlsx"],
        help="Must contain at least an email column"
    )

    email_column = None
    personalization_columns = []
    df_recipients = None
    enable_personalize = False

    if excel_file:
        try:
            df_recipients = pd.read_excel(excel_file)
            st.success(f"Loaded {len(df_recipients)} rows")

            # Auto-detect email column
            detected_col = detect_email_column(df_recipients)
            if detected_col:
                email_column = detected_col
                st.success(f"Auto-detected email column: **{email_column}**")
            else:
                st.warning("Could not auto-detect email column.")
                email_column = st.selectbox(
                    "Select the email column",
                    options=df_recipients.columns,
                    help="Column containing recipient email addresses"
                )

            # Personalization options
            personalization_columns = get_personalization_columns(df_recipients)
            if personalization_columns:
                enable_personalize = st.checkbox(
                    f"Personalize greeting (found: {', '.join(personalization_columns)})",
                    value=False,
                    help="Replace {{variable}} with actual values from Excel"
                )

            # Email selection options
            st.subheader("Select Recipients")
            col_sel1, col_sel2, col_sel3 = st.columns([1, 1, 0.8])
            
            # Initialize session state for selections
            if "selected_emails" not in st.session_state:
                st.session_state.selected_emails = set(df_recipients[email_column].unique())
            
            unique_emails = sorted(df_recipients[email_column].unique())
            
            with col_sel1:
                if st.button("Select All", use_container_width=True):
                    st.session_state.selected_emails = set(unique_emails)
                    # Also update individual checkbox states
                    for email in unique_emails:
                        st.session_state[f"email_checkbox_{email}"] = True
                    st.rerun()
            
            with col_sel2:
                if st.button("Deselect All", use_container_width=True):
                    st.session_state.selected_emails = set()
                    # Also clear individual checkbox states
                    for email in unique_emails:
                        st.session_state[f"email_checkbox_{email}"] = False
                    st.rerun()
            
            # Create placeholder for counter in col_sel3 (will be updated after checkbox collection)
            counter_placeholder = col_sel3.empty()
            
            # Search bar for filtering emails
            search_query = st.text_input("Search emails:", placeholder="Type email to filter...")
            
            # Filter emails based on search query
            filtered_emails = [email for email in unique_emails if search_query.lower() in email.lower()] if search_query else unique_emails
            
            # Checkbox-based email selection for clean UI
            st.write("**Check boxes below to select recipients:**")
            
            # Create columns for checkbox layout
            num_cols = 3  # Number of columns for checkboxes
            cols = st.columns(num_cols)
            
            selected_emails = []
            for idx, email in enumerate(filtered_emails):
                col_idx = idx % num_cols
                with cols[col_idx]:
                    is_checked = st.checkbox(
                        email,
                        value=(email in st.session_state.selected_emails),
                        key=f"email_checkbox_{email}"
                    )
                    if is_checked:
                        selected_emails.append(email)
            
            # Update session state with current selections (triggers real-time update)
            st.session_state.selected_emails = set(selected_emails)
            
            # Update counter placeholder with real-time selection count
            count_display = len(st.session_state.selected_emails)
            total_display = len(unique_emails)
            with counter_placeholder:
                st.metric("Selected", f"{count_display}/{total_display}")
            
            # Filter dataframe to selected emails only
            if selected_emails:
                df_recipients_filtered = df_recipients[df_recipients[email_column].isin(selected_emails)].copy()
                st.success(f"Will send to {len(df_recipients_filtered)} of {len(df_recipients)} recipients")
            else:
                df_recipients_filtered = df_recipients.copy()
                st.warning("No recipients selected!")

            # Preview first few rows
            with st.expander("Preview Data (first 5 rows)"):
                st.dataframe(df_recipients.head(5), use_container_width=True)

        except Exception as e:
            st.error(f"Error reading Excel: {str(e)}")
            df_recipients = None

    # ========================================================================
    # VALIDATION & SAFETY CHECKS
    # ========================================================================
    def validate_inputs() -> Tuple[bool, str]:
        """Validate all inputs before sending."""
        if not from_email or "@" not in from_email:
            return False, "Valid Gmail address required"
        if not app_password or len(app_password) < 16:
            return False, "App Password (16 chars) required"
        if not subject:
            return False, "Subject required"
        if not email_body:
            return False, "Email body required"
        if df_recipients is None or len(df_recipients) == 0:
            return False, "No recipients loaded"
        if email_column is None:
            return False, "Email column not selected"
        if not selected_emails:
            return False, "No recipients selected"
        if len(df_recipients_filtered) > max_emails:
            return False, f"{len(df_recipients_filtered)} selected emails exceed limit of {max_emails}"
        return True, ""

    # ========================================================================
    # PREVIEW & SEND BUTTONS
    # ========================================================================
    col_preview, col_send = st.columns([1, 1])

    with col_preview:
        if st.button("Preview", use_container_width=True, type="secondary"):
            valid, error_msg = validate_inputs()
            if not valid:
                st.error(error_msg)
            else:
                # Show preview
                preview_recipients = df_recipients_filtered[email_column].head(3).tolist()
                st.session_state.preview_data = {
                    "subject": subject,
                    "body": email_body,
                    "recipients": preview_recipients,
                    "attachments": [f.name for f in attachment_files] if attachment_files else [],
                }

                st.divider()
                st.subheader(f"Preview: First 3 of {len(df_recipients_filtered)} Selected Recipients")
                for idx, email in enumerate(st.session_state.preview_data["recipients"], 1):
                    with st.expander(f"Email {idx}: {email}"):
                        row_data = {col: str(df_recipients_filtered[df_recipients_filtered[email_column] == email][col].values[0]) 
                                   for col in personalization_columns if enable_personalize}
                        row_data["email"] = email
                        preview_body = replace_template_variables(email_body, row_data)

                        st.write(f"**To:** {email}")
                        st.write(f"**Subject:** {subject}")
                        st.write("**Body:**")
                        st.text(preview_body)

                if st.session_state.preview_data["attachments"]:
                    st.write(f"**Attachments:** {', '.join(st.session_state.preview_data['attachments'])}")

    with col_send:
        if st.button(
            "Send All",
            use_container_width=True,
            type="primary",
            help="One-click send to all selected recipients"
        ):
            valid, error_msg = validate_inputs()
            if not valid:
                st.error(error_msg)
            else:
                # EXECUTE SEND
                send_all_emails(
                    from_email=from_email,
                    app_password=app_password,
                    df=df_recipients_filtered,
                    email_column=email_column,
                    subject=subject,
                    body=email_body,
                    attachment_files=attachment_files,
                    send_delay=send_delay,
                    enable_personalize=enable_personalize,
                    personalization_columns=personalization_columns,
                    is_html=is_html,
                    signature=signature,
                    max_emails=max_emails
                )

    # ========================================================================
    # RESULTS DISPLAY
    # ========================================================================
    if st.session_state.send_results is not None:
        st.divider()
        st.header("Send Results")
        results_df = pd.DataFrame(st.session_state.send_results)
        
        success_count = (results_df["status"] == "Sent").sum()
        failed_count = (results_df["status"] == "Failed").sum()
        invalid_count = (results_df["status"] == "Invalid Email").sum()

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Sent", success_count, delta="emails")
        with col2:
            st.metric("Failed", failed_count)
        with col3:
            st.metric("Invalid", invalid_count)

        st.dataframe(results_df, use_container_width=True, hide_index=True)

        # Download results as CSV
        csv = results_df.to_csv(index=False)
        st.download_button(
            label="Download Results (CSV)",
            data=csv,
            file_name="send_results.csv",
            mime="text/csv"
        )


def send_all_emails(
    from_email: str,
    app_password: str,
    df: pd.DataFrame,
    email_column: str,
    subject: str,
    body: str,
    attachment_files: List,
    send_delay: int,
    enable_personalize: bool,
    personalization_columns: List[str],
    is_html: bool,
    signature: str,
    max_emails: int
) -> None:
    """
    Execute sending emails to all recipients.
    Updates session state with results.
    """
    # Prepare recipients
    df_send = df.copy()
    if len(df_send) > max_emails:
        df_send = df_send.head(max_emails)

    # Deduplication
    df_send = deduplicate_emails(df_send, email_column)

    # Validate and filter emails
    df_send["valid_email"] = df_send[email_column].apply(validate_email)

    # Prepare attachments
    attachments = prepare_attachments(attachment_files)

    # Progress tracking
    progress_bar = st.progress(0)
    log_area = st.empty()
    results = []

    st.info(f"Sending {len(df_send)} emails with {send_delay}s delay...")

    for idx, row in df_send.iterrows():
        email = row[email_column]
        row_num = idx + 1

        # Check valid email
        if not row["valid_email"]:
            results.append({
                "email": email,
                "status": "Invalid Email",
                "error_message": "Invalid email format"
            })
            log_area.info(f"[{row_num}] Invalid: {email}")
            continue

        # Build personalization data
        row_data = {"email": email}
        if enable_personalize:
            for col in personalization_columns:
                if col in df_send.columns:
                    row_data[col] = row[col]

        # Replace template variables
        personalized_body = replace_template_variables(body, row_data)

        # Build and send email
        try:
            msg = build_email_message(
                from_email=from_email,
                to_email=email,
                subject=subject,
                body=personalized_body,
                attachments=attachments,
                is_html=is_html,
                signature=signature
            )
            success, error_msg = send_email_smtp(
                from_email=from_email,
                app_password=app_password,
                to_email=email,
                message=msg
            )

            if success:
                results.append({
                    "email": email,
                    "status": "Sent",
                    "error_message": ""
                })
                log_area.info(f"[{row_num}/{len(df_send)}] Sent to {email}")
            else:
                results.append({
                    "email": email,
                    "status": "Failed",
                    "error_message": error_msg
                })
                log_area.warning(f"[{row_num}/{len(df_send)}] Failed: {email} - {error_msg}")

        except Exception as e:
            error_msg = f"Exception: {str(e)[:100]}"
            results.append({
                "email": email,
                "status": "Failed",
                "error_message": error_msg
            })
            log_area.error(f"[{row_num}/{len(df_send)}] Error: {email} - {error_msg}")

        # Progress update
        progress = min(1.0, (idx + 1) / max(1, len(df_send)))
        progress_bar.progress(progress)

        # Delay between sends (except last)
        if idx < len(df_send) - 1:
            time.sleep(send_delay)

    # Final summary
    st.session_state.send_results = results
    st.success("Bulk send complete!")


if __name__ == "__main__":
    main()
