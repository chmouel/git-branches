# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability within git-branches, please send an email to [your-email@example.com]. All security vulnerabilities will be promptly addressed.

Please include the following information in your report:

- A description of the vulnerability
- Steps to reproduce the issue
- Potential impact
- Suggested fix (if any)

## Security Considerations

- This tool requires access to your local git repository
- When using GitHub integration, it may store GitHub tokens in environment variables or password managers
- The tool caches PR data locally in `~/.cache/git-branches/prs.json`
- No sensitive data is transmitted to external services except GitHub API calls when enabled

## Best Practices

1. Keep your GitHub token secure and use fine-grained tokens with minimal permissions
2. Regularly update the tool to get security patches
3. Review the cached data in `~/.cache/git-branches/` if needed
4. Run the tool only in trusted git repositories
