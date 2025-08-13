# Contributing to git-branches

Thank you for your interest in contributing to git-branches! This document provides guidelines for contributing to the project.

## Development Setup

1. Fork and clone the repository
2. Install development dependencies:
   ```bash
   make install
   ```
3. Run the development environment:
   ```bash
   make dev
   ```

## Code Style

- Follow the existing code style (enforced by ruff)
- Use type hints for all function parameters and return values
- Write docstrings for public functions
- Keep functions focused and small
- Use meaningful variable names

## Testing

- Write tests for new features and bug fixes
- Ensure all tests pass: `make test`
- Use `monkeypatch` to mock external dependencies
- Test both success and error cases

## Pull Request Process

1. Create a feature branch from `main`
2. Make your changes following the coding guidelines
3. Add tests for new functionality
4. Ensure all tests pass: `make test`
5. Run linting and formatting: `make dev`
6. Update documentation if needed
7. Submit a pull request with a clear description

## Commit Messages

Use conventional commit format:
```
type(scope): description

[optional body]

[optional footer]
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes
- `refactor`: Code refactoring
- `test`: Test changes
- `chore`: Maintenance tasks

## Issue Reporting

When reporting issues, please include:
- Operating system and version
- Python version
- Steps to reproduce
- Expected vs actual behavior
- Any error messages

## Feature Requests

For feature requests, please:
- Describe the use case
- Explain why this would be useful
- Consider if it fits the project's scope
- Suggest implementation approach if possible

## Questions?

Feel free to open an issue for questions or discussions about the project.
