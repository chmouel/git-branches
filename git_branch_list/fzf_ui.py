from __future__ import annotations

import subprocess

from .git_ops import run


def fzf_select(
    rows: list[tuple[str, str]],
    header: str,
    preview_cmd: list[str] | None,
    multi: bool = False,
    extra_binds: list[str] | None = None,
) -> list[str]:
    if not rows:
        return []
    import shlex

    input_text = "\n".join(f"{shown}\t{value}" for shown, value in rows)
    cmd = [
        "fzf",
        "--reverse",
        "--ansi",
        "--delimiter=\t",
        "--with-nth=1",
        "--header",
        header,
        "--preview-window=top:50%",
    ]
    if preview_cmd:
        cmd.extend(["--preview", " ".join(shlex.quote(x) for x in preview_cmd)])
    if multi:
        cmd.append("--multi")
    if extra_binds:
        for b in extra_binds:
            cmd.extend(["--bind", b])

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write(input_text)
    proc.stdin.close()
    out = proc.stdout.read() or ""
    proc.wait()
    selected: list[str] = []
    for line in out.splitlines():
        if "\t" in line:
            selected.append(line.split("\t", 1)[1])
    return selected


def confirm(prompt: str) -> bool:
    try:
        answer = input(f"{prompt} [y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


def select_remote() -> str:
    cp = run(["git", "remote"])
    remotes = [r for r in cp.stdout.splitlines() if r.strip()]
    if not remotes:
        return ""
    proc = subprocess.Popen(
        [
            "fzf",
            "-1",
            "--height=10",
            "--reverse",
            "--prompt=Select remote: ",
            "--preview",
            "git remote get-url {}",
            "--preview-window=down:2:wrap",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert proc.stdin and proc.stdout
    proc.stdin.write("\n".join(remotes))
    proc.stdin.close()
    remote = (proc.stdout.read() or "").strip()
    proc.wait()
    return remote
