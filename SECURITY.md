# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| Latest  | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability, please **do not** open a public issue.

### How to Report

1. **Email**: Send details to the repository owner via GitHub profile
2. **Private vulnerability reporting**: Use GitHub's private vulnerability reporting feature

### What to Include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response Timeline

- **Acknowledgment**: Within 48 hours
- **Status update**: Within 7 days
- **Resolution**: As soon as possible, depending on severity

## Security Best Practices

When deploying DeepSeek-Monitor:

1. **Never expose the monitoring service to public networks**
2. **Use environment variables** for all credentials (API keys, passwords)
3. **Run with minimal privileges** — do not run as root
4. **Keep dependencies updated** — run `pip-audit -r requirements.txt` regularly
5. **Review command whitelist** — only allow necessary commands in the whitelist
6. **Enable logging** — monitor for suspicious activity

## Dependency Security

This project uses `pip-audit` to scan for known CVEs in dependencies. Run:

```bash
pip install pip-audit
pip-audit -r requirements.txt
```

## Code Security

- All command execution goes through a **whitelist** mechanism
- `shell=True` is **prohibited** — all subprocess calls use argument lists
- Sensitive configuration values are **masked in logs**
- Selenium WebDriver interactions use **explicit waits** and **error handling**

---

Thank you for helping keep DeepSeek-Monitor secure!
