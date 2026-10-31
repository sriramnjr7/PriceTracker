---
name: cso
description: Chief Security Officer audit covering OWASP Top 10, STRIDE threat models, and secret exposure.
triggers:
  - cso
  - security audit
  - security review
  - check vulnerabilities
---

# CSO (Chief Security Officer) Audit Skill

When invoked, execute a structured security audit:

1. **Secret & Credential Leak Check**: Scan files, `.env`, configs, logs, and database files for hardcoded API keys, passwords, or tokens.
2. **Input Validation & Injection**: Ensure SQL queries use parameterized queries (e.g. SQLite `?`), URLs are properly validated, and external inputs sanitized.
3. **Bot / Anti-Scraping Compliance**: Ensure user-agent rotation and delays prevent IP bans; verify error handling doesn't leak internal paths or stack traces.
4. **Threat Model (STRIDE)**:
   - Spoofing, Tampering, Repudiation, Information Disclosure, Denial of Service, Elevation of Privilege.
5. **Output**: Deliver findings categorized as Critical, Warning, or Info with actionable remediations.
