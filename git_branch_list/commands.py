import shutil
import subprocess


def which(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def run(cmd: list[str], cwd: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """
    Runs a command using subprocess.run and returns the CompletedProcess object.
    Raises CalledProcessError if check=True and the command fails.
    """
    return subprocess.run(
        cmd,
        capture_output=True,
        cwd=cwd,
        check=check,
        text=True,
    )
