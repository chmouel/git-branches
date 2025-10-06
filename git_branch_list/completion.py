import os
import subprocess
import sys

import click

from .cli import cli


@cli.command(name="completion", help="Generate shell completion script")
@click.option(
    "--shell",
    "shell_",
    type=click.Choice(["bash", "zsh", "fish", "pwsh"], case_sensitive=False),
    help="Target shell (auto-detect if omitted)",
)
def completion(shell_: str | None):
    prog = os.path.basename(sys.argv[0]) or "git-branches"
    # auto-detect shell from env if not provided
    if not shell_:
        shpath = os.environ.get("SHELL", "")
        if "zsh" in shpath:
            shell_ = "zsh"
        elif "fish" in shpath:
            shell_ = "fish"
        elif "pwsh" in shpath or "powershell" in shpath:
            shell_ = "pwsh"
        else:
            shell_ = "bash"

    suffix = {
        "bash": "bash_source",
        "zsh": "zsh_source",
        "fish": "fish_source",
        "pwsh": "pwsh_source",
    }[shell_]

    # Click uses the _PROG_COMPLETE protocol to emit completion scripts
    env_var = f"_{prog.replace('-', '_').upper()}_COMPLETE"
    env = os.environ.copy()
    env[env_var] = suffix
    try:
        cp = subprocess.run([prog], env=env, check=True, capture_output=True, text=True)
        sys.stdout.write(cp.stdout)
    except Exception as exc:
        print(f"Error generating completion for {shell_}: {exc}", file=sys.stderr)
        sys.exit(1)
