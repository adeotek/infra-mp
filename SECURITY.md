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

- **Always set a strong `INFRAMP_SECRET_KEY`** (see `.env.example`) — it signs
  the CSRF tokens every state-changing request validates.
- Never expose the instance to the internet without a reverse proxy with TLS.
- Never enable `INFRAMP_DEBUG=true` in production.
- Set `INFRAMP_ALLOWED_HOSTS` to your real hostnames when running behind a
  reverse proxy; enable `INFRAMP_HSTS_ENABLED` only when TLS terminates there.
- When `INFRAMP_ADMIN_PASSWORD` is empty, the seeded admin's random password is
  printed to stdout once — it is visible in container logs (and any log
  collector). Change it immediately after first login.
- The container runs as non-root uid 10001; on upgrades from pre-0.7.0 images,
  chown the data volume once (see README).
