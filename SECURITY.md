# Security Policy

## Supported versions

Only the latest release is supported with security fixes. We do not backport
fixes to older releases.

| Version | Supported |
| --- | --- |
| latest (published image / `main`) | ✅ |
| older releases | ❌ |

## Reporting a vulnerability

Please **do not open a public issue** for security vulnerabilities.

Report them privately instead:

1. Use GitHub's **private vulnerability reporting** — go to
   **Security → Advisories → Report a vulnerability** on the repository.
2. Or email **george.benjamin@gmail.com** with the details.

Please include:

- The affected version(s).
- A description of the vulnerability and its potential impact.
- Steps to reproduce, or a proof of concept if you have one.
- Any suggested fix.

You will receive an acknowledgement within a few days, and we aim to publish a
fix as soon as possible. We'll credit reporters who wish to be named in the
advisory.

## What to expect

- **Supported**: authentication bypass, privilege escalation (RBAC), SQL/NoSQL
  injection, XSS, CSRF, data leakage between users, secrets exposure.
- **Out of scope**: issues that require an already-admin attacker, DoS from
  untrusted LAN access, or vulnerabilities in dependencies not directly
  exploitable through InfraMP.

## Deployment notes

- **Always set a strong `INFRAMP_SECRET_KEY`** (see `.env.example`).
- Never expose the instance to the internet without a reverse proxy with TLS.
- Never enable `INFRAMP_DEBUG=true` in production.
