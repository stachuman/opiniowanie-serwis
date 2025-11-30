# Security Setup Guide

## ⚠️ IMPORTANT: Protecting Sensitive Credentials

This document explains how to properly configure sensitive credentials for the Court Document Management System without exposing them in git.

---

## Quick Setup (First Time)

### 1. Install python-dotenv (if not installed)

```bash
conda activate court-workflow
pip install python-dotenv
```

### 2. Create your local `.env` file

```bash
# Copy the example template
cp .env.example .env

# Edit with your actual credentials
nano .env  # or vim, or any text editor
```

### 3. Fill in your credentials

Edit `.env` and replace placeholder values with your actual credentials:

```bash
# Gmail SMTP credentials
SMTP_USER=your-actual-email@gmail.com
SMTP_PASSWORD=your-actual-app-password

# Default recipient
DEFAULT_EMAIL=recipient@example.com

# Server URL
SERVER_URL=http://your-server-ip
```

---

## Gmail App Password Setup

**NEVER use your regular Gmail password!** Use an App Password instead:

1. Go to: https://myaccount.google.com/apppasswords
2. Sign in to your Google Account
3. Select "Mail" as the app
4. Select "Other" as the device, enter "Court System"
5. Click "Generate"
6. Copy the 16-character password (format: `xxxx xxxx xxxx xxxx`)
7. Paste it into `.env` as `SMTP_PASSWORD` (with or without spaces)

---

## Security Best Practices

### ✅ DO:
- ✅ Keep `.env` file LOCAL ONLY (never commit to git)
- ✅ Use `.env.example` as a template (safe to commit)
- ✅ Use Gmail App Passwords (not your regular password)
- ✅ Set restrictive file permissions: `chmod 600 .env`
- ✅ Rotate credentials periodically
- ✅ Use different credentials for dev/staging/production

### ❌ DON'T:
- ❌ Never commit `.env` to git
- ❌ Never hardcode credentials in `.py` files
- ❌ Never share `.env` file via email/chat
- ❌ Never use your regular Gmail password
- ❌ Never commit files matching `*.secret`, `credentials.json`

---

## Files Protected by .gitignore

The following files are automatically ignored by git (safe to store secrets):

```
.env                    # Your local environment variables
.env.local             # Alternative local config
.env.*.local           # Environment-specific configs
*.secret               # Any file ending in .secret
credentials.json       # Google/AWS credentials
secrets.json           # Generic secrets file
```

---

## Environment Variables Reference

### Email Configuration
| Variable | Required | Example | Description |
|----------|----------|---------|-------------|
| `SMTP_USER` | ✅ Yes | `user@gmail.com` | Gmail account for sending |
| `SMTP_PASSWORD` | ✅ Yes | `xxxx xxxx xxxx xxxx` | Gmail App Password |
| `DEFAULT_EMAIL` | ⚠️  Optional | `recipient@example.com` | Default recipient |
| `SERVER_URL` | ⚠️  Optional | `http://192.168.1.218` | Server URL for links |

### OCR Configuration
| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OCR_GPU_SELECT` | No | `auto` | GPU selection mode |
| `OCR_DEVICE_STRATEGY` | No | `single` | Device distribution strategy |
| `OCR_GPU_MEM_LIMIT_GB` | No | `22` | GPU memory limit in GB |

### Orientation Detection
| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ORIENTATION_DETECTION_ENABLED` | No | `true` | Enable/disable ML orientation |
| `ORIENTATION_GPU_THRESHOLD_GB` | No | `8` | GPU memory threshold in GB |
| `ORIENTATION_TIMEOUT_SEC` | No | `5` | Inference timeout in seconds |
| `ORIENTATION_MIN_CONFIDENCE` | No | `0.7` | Minimum confidence threshold |

---

## Troubleshooting

### Error: "SMTP credentials not set"

**Cause**: `.env` file not loaded or environment variables not set

**Solution**:
1. Verify `.env` file exists: `ls -la /root/court/.env`
2. Check file contents: `cat /root/court/.env` (verify SMTP_USER and SMTP_PASSWORD are set)
3. Restart the application to reload environment variables
4. Check logs for: `✅ [MAIN] Loaded environment variables from .env`

### Error: "Authentication failed" when sending email

**Cause**: Incorrect Gmail App Password or 2FA not enabled

**Solution**:
1. Verify you're using an App Password (NOT your regular password)
2. Enable 2-Factor Authentication on your Google Account
3. Generate a new App Password at https://myaccount.google.com/apppasswords
4. Update `SMTP_PASSWORD` in `.env`
5. Restart application

### Error: python-dotenv not found

**Cause**: `python-dotenv` package not installed

**Solution**:
```bash
conda activate court-workflow
pip install python-dotenv
```

---

## Testing Email Configuration

Test if credentials are loaded correctly:

```bash
conda activate court-workflow
python -c "
from app.config.email_config import SMTP_USER, SMTP_PASSWORD, DEFAULT_EMAIL
print(f'SMTP_USER: {SMTP_USER}')
print(f'SMTP_PASSWORD: {'*' * len(SMTP_PASSWORD) if SMTP_PASSWORD else 'NOT SET'}')
print(f'DEFAULT_EMAIL: {DEFAULT_EMAIL}')
"
```

Expected output:
```
SMTP_USER: your-email@gmail.com
SMTP_PASSWORD: ****************
DEFAULT_EMAIL: recipient@example.com
```

---

## Deployment Checklist

Before deploying to a new server:

- [ ] Copy `.env.example` to `.env`
- [ ] Fill in all required credentials in `.env`
- [ ] Set file permissions: `chmod 600 .env`
- [ ] Verify `.env` is in `.gitignore`
- [ ] Install python-dotenv: `pip install python-dotenv`
- [ ] Test email configuration (see above)
- [ ] Restart application to load new variables
- [ ] Verify email functionality works

---

## Emergency: Credentials Leaked to Git

If you accidentally committed credentials to git:

### 1. Remove from latest commit (not yet pushed)
```bash
git reset HEAD~1
# Edit files to remove credentials
git add .
git commit -m "Remove sensitive credentials"
```

### 2. Already pushed to GitHub
```bash
# Change the exposed password IMMEDIATELY:
# 1. Revoke the Gmail App Password
# 2. Generate new App Password
# 3. Update .env with new password

# Remove from git history (DANGEROUS - coordinate with team):
git filter-branch --force --index-filter \
  "git rm --cached --ignore-unmatch app/config/email_config.py" \
  --prune-empty --tag-name-filter cat -- --all

# Force push (WARNING: rewrites history)
git push origin --force --all
```

### 3. Notify
- Revoke compromised credentials immediately
- Generate new credentials
- Update `.env` on all servers
- Consider enabling GitHub secret scanning

---

## Additional Resources

- [Gmail App Passwords](https://support.google.com/accounts/answer/185833)
- [python-dotenv Documentation](https://github.com/theskumar/python-dotenv)
- [Git Secrets Protection](https://git-scm.com/book/en/v2/Git-Tools-Credential-Storage)
