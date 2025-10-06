from __future__ import annotations

import subprocess

from .commands import run


def fzf_select(
    rows: list[tuple[str, str]],
    header: str,
    preview_cmd: list[str] | None,
    multi: bool = False,
    extra_binds: list[str] | None = None,
    expect_keys: list[str] | None = None,
) -> list[str] | tuple[str | None, list[str]]:
    if not rows:
        return []
    import shlex

    input_text = "\n".join(f"{shown}\t{value}" for shown, value in rows)

    # Enhanced fzf styling for better visual appearance
    cmd = [
        "fzf",
        "--reverse",
        "--ansi",
        "--delimiter=\t",
        "--with-nth=1",
        "--footer",
        header,
        "--preview-window=bottom:75%:nohidden:wrap",
        "--border=rounded",
        "--color=footer:italic:bold,border:magenta,prompt:bright-magenta,pointer:bright-cyan,marker:bright-cyan",
        "--prompt=❯ ",
        "--pointer=❯",
        "--marker=•",
    ]

    # Default key bindings for better navigation
    default_binds = [
        "alt-n:next-history",
        "alt-p:previous-history",
        "ctrl-j:preview-down",
        "ctrl-k:preview-up",
        "ctrl-n:down",
        "ctrl-p:up",
        "ctrl-d:change-preview-window(right:wrap|down,70%:wrap)",
        "ctrl-u:preview-half-page-up",
    ]

    if preview_cmd:
        cmd.extend(["--preview", " ".join(shlex.quote(x) for x in preview_cmd)])
    if multi:
        cmd.append("--multi")

    # Combine default binds with extra binds
    all_binds = default_binds[:]
    if extra_binds:
        all_binds.extend(extra_binds)

    if all_binds:
        cmd.extend(["--bind", ",".join(all_binds)])

    if expect_keys:
        cmd.extend(["--expect", ",".join(expect_keys)])

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write(input_text)
    proc.stdin.close()
    out = proc.stdout.read() or ""
    proc.wait()
    lines = out.splitlines()
    selected: list[str] = []
    key_pressed: str | None = None
    start_idx = 0
    if expect_keys:
        if lines:
            key_pressed = lines[0] or None
            start_idx = 1
        else:
            key_pressed = None
    for line in lines[start_idx:]:
        if "\t" in line:
            selected.append(line.split("\t", 1)[1])
    if expect_keys:
        return key_pressed, selected
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
            "--border=rounded",
            "--color=footer:italic:bold,border:magenta,prompt:bright-magenta,pointer:bright-cyan,marker:bright-cyan",
            "--prompt=❯ Select remote: ",
            "--pointer=❯",
            "--marker=•",
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
