# Bulk Email Sender

This is a Streamlit app for sending personalized bulk emails to multiple recipients using Gmail SMTP with an App Password.

---

## Features

- **One-click sending**: Send to 100+ recipients with a single button
- **Template variables**: Personalize emails with `{{name}}`, `{{company}}`, and more
- **Email validation**: Detects and skips invalid email addresses
- **Safety limits**: Hard cap on emails per run (default 150, configurable)
- **File attachments**: Attach PDF, DOCX, images, and more
- **HTML or plain text**: Choose the email format
- **Progress tracking**: Live log and progress bar while sending
- **Results export**: Download send results as CSV
- **Smart Excel parsing**: Detects the email column and available personalization fields
- **Duplicate handling**: Optional deduplication by email address
- **Anti-spam delays**: Configurable delays between sends
- **Credentials kept in memory**: No passwords stored to disk

---

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Create a Gmail App Password

**Required:** Gmail account with 2-Step Verification enabled.

1. Go to [myaccount.google.com/security](https://myaccount.google.com/security)
2. Scroll to **"How you sign in to Google"** and enable **2-Step Verification** (if not already on)
3. Go back to **Security** and scroll to **App passwords** (appears only if 2FA is on)
4. Select **Mail** and **Windows/Mac/Linux**
5. Copy the **16-character password** (you'll paste this into the app)

> Never share your App Password. Treat it like your main password.

### 3. Prepare Your Excel File

Create an `.xlsx` file with recipient data. **Minimum requirement:** one column with email addresses.

**Example format:**

| email                | name          | company           | first_name |
|----------------------|---------------|-------------------|-----------|
| john@acme.com        | John Smith    | Acme Corp         | John      |
| jane@techstart.io    | Jane Doe      | TechStart Inc     | Jane      |
| bob@innovate.com     | Bob Johnson   | Innovate Labs     | Bob       |

**Supported columns for auto-personalization:**
- `name`, `first_name`, `last_name`
- `company`, `organization`
- `email` (auto-detected)

### 4. Run the App

```bash
streamlit run app.py
```

The app opens in your browser at `http://localhost:8501`.

---

## How to Use

### Step 1: Configure Gmail
- Enter your **Gmail address** (sidebar)
- Paste your **App Password** (16 chars from step 2 above)

### Step 2: Compose Email
- **Subject:** Email subject line
- **Email Body:** Write your message. Use `{{name}}`, `{{company}}` for personalization
- **Optional Signature:** Appended to all emails

### Step 3: Add Attachments (Optional)
- Upload files: PDF, DOCX, images, etc.
- All attached files go to every recipient

### Step 4: Upload Recipients
- Click "Upload Excel File (.xlsx)"
- App auto-detects email column
- If not detected, manually select from dropdown
- Check "Personalize greeting" to enable template variables

### Step 5: Preview (Recommended)
- Click **"Preview"** to see the first 3 rendered emails
- Verify subject, body, and attachment names
- **No emails sent during preview**

### Step 6: Send
- Click **"Send All"** to execute
- Watch live progress and logs
- Review results table with status per recipient
- Download CSV for records

---

## Configuration Options (Sidebar)

| Setting | Default | Purpose |
|---------|---------|---------|
| **Delay between emails** | 3 sec | Reduces spam flagging |
| **Max emails per run** | 150 | Safety limit; can increase |
| **Deduplicate emails** | On | Remove duplicate addresses |
| **Send as HTML** | Off | Enable for styled emails |
| **Signature** | (empty) | Auto-appended to all emails |

---

## User Interface

The app uses a simple two-part layout.

### Sidebar
- Gmail address and App Password input
- Sending controls (delay, max emails per run, deduplication)
- Email formatting options (HTML on/off)
- Optional signature

### Main page
- Subject and email body editor
- Attachment uploader (optional)
- Recipient Excel uploader and column selection (if auto-detect fails)
- Preview section to render a small sample before sending
- Send button with progress and live logs

### Results
- Summary counts and a per-recipient status table
- CSV export of the send results

## Sample Use Cases

### Case 1: Job Application Outreach
**Excel columns:** `email`, `company`, `name`

**Email template:**
```
Subject: Exciting Opportunity at {{company}}

Dear {{name}},

I came across {{company}} and was impressed by your work.
I'd love to discuss how I can contribute.

Attachments: Resume, Portfolio

Best regards,
Alice
```

### Case 2: Newsletter to Employers
**Excel columns:** `email`, `first_name`

**Email template:**
```
Subject: Q4 Newsletter - Industry Insights

Hi {{first_name}},

Here's this quarter's roundup...

Attachments: Newsletter PDF
```

---

## Test with Sample Data (Safe Testing)

**Before sending to real recipients, test with your own email:**

1. Create `test.xlsx` with just your email address:
   ```
   email
   your.email@gmail.com
   ```

2. In the app:
   - Set **Max emails per run** to 5
   - Use a test subject: `[TEST] Bulk Email App`
   - Click **"Preview"** — verify everything looks right
   - Click **"Send All"** — send 1 email to yourself
   - Check your inbox and spam folder

3. Review email formatting, attachments, and personalization

4. Once verified, create your full recipient list and proceed

---

## Safety and Best Practices

### Spam Prevention
- **Default 3-second delay** between emails reduces spam flags
- **Preview first** before sending bulk
- **Start small:** Test with 10–20 recipients before scaling
- **Unique content:** Avoid identical mass emails; use template variables
- **Clean list:** Remove bounced/invalid addresses

### Gmail Sending Limits
- **Daily limit:** ~500 emails/day for new accounts (increases over time)
- **Rate limit:** ~100 emails/minute
- **App Password only:** Cannot use primary password with SMTP

### Security
- **No credentials stored:** App Password exists in memory only
- **Use 2FA:** Required for App Password generation
- **Revoke anytime:** Visit Gmail Security Settings to delete compromised App Passwords

### Recipient List
- Use verified, opted-in email lists
- Honor unsubscribe requests
- Never scrape email lists without consent
- Avoid purchased or untargeted lists

---

## Results and Logging

After sending, you'll see:
- **Summary metrics:** Sent | Failed | Invalid
- **Per-recipient status table** with errors for failed sends
- **CSV download** for record-keeping and auditing

**Common error messages:**
| Error | Cause | Fix |
|-------|-------|-----|
| Authentication failed | Wrong App Password | Regenerate at Gmail Security |
| SMTP error: 534 | Gmail blocked login | Enable 2FA and use App Password |
| Invalid email format | Bad email in Excel | Fix in source Excel file |

---

## Advanced: Optional Gmail API (OAuth)

The main app uses **SMTP** (fast, simple, no setup).

**For future enhancement**, a Gmail API + OAuth module would provide:
- No App Password needed
- Batch sending capability
- Better rate limit management
- Scheduled sends

**Implementation notes** (not included in base app):
```python
# Pseudo-code structure for future OAuth implementation
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials
from google.auth.oauthlib.flow import InstalledAppFlow

# Enable Gmail API in Google Cloud Console
# Download credentials JSON
# Implement OAuth2 flow
# Use gmail.users().messages().send() for batch operations
```

This requires Google Cloud project setup but provides more robust production capabilities.

---

## File Attachment Support

**Allowed types:** PDF, DOCX, DOC, TXT, PNG, JPG, JPEG, XLSX

**Tips:**
- Keep files 10MB or less total per email (Gmail limit)
- Use descriptive filenames
- Test attachment delivery with preview

---

## Troubleshooting

### App won't start
```bash
pip install -r requirements.txt --upgrade
streamlit run app.py
```

### "ModuleNotFoundError: No module named 'streamlit'"
```bash
pip install streamlit pandas openpyxl
```

### Authentication fails after correct App Password
- Ensure 2-Step Verification is enabled on your Gmail account
- Regenerate the App Password (the old one may have been revoked)
- Copy the full 16-character string (no spaces)

### Email not received
- Check recipient spam folder
- Verify email address in preview
- Try sending test to yourself first
- Check Gmail activity/security alerts

---

## Version and License

**Version:** 1.0.0  
**Python:** 3.10+  
**License:** MIT (free to use and modify)

---

## Support and Feedback

For issues or feature requests:
1. Check the **Troubleshooting** section above
2. Review logs in the app's **Send Results** area
3. Test with sample data first
4. Verify Gmail credentials and account settings

---

## Next Steps

1. **Install:** `pip install -r requirements.txt`
2. **Create App Password:** Follow Gmail Security setup above
3. **Test:** Run with sample data to yourself
4. **Launch:** `streamlit run app.py` and start sending

If you run into issues, check the Troubleshooting section and review the in-app logs.
