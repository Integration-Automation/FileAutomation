# Security policy

## Supported versions

Security fixes are provided for the latest release and the default
branch. Older releases are not supported. Upgrade before reporting
an issue that may already be fixed.

## Reporting a vulnerability

Do not open a public issue, pull request, or discussion for a suspected
vulnerability.

Use either private channel:

- **GitHub Security Advisories.** Open a private report from this
  repository's Security tab, **Report a vulnerability**. This is the
  preferred channel.
- **Email.** `jechenmailman@gmail.com`, with a subject line that begins
  with `[SECURITY]`.

Include the affected version, platform, impact, and steps to reproduce.
Do not attach credentials, tokens, or unredacted logs.

The maintainers aim to acknowledge a report within 5 business days, and
to coordinate a fix and disclosure within 90 days. There is no bug-bounty
promise.

## Operational notes

Treat archive members as untrusted paths. Do not extract an archive from a
source you do not trust until extraction is confined to the directory you
chose.

A secrets provider reads files. Give it only a root it is allowed to read.
An SFTP or FTP root is a path prefix, not a jail.

A device-code login places the access token in the result and in the GUI
log. Do not share either.
