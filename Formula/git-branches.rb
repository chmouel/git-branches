class GitBranches < Formula

  desc "Interactive Git branch browser with fzf and GitHub PR status"
  homepage "https://github.com/chmouel/git-branches"
  head "https://github.com/chmouel/git-branches.git", branch: "main"
  license "Apache-2.0"

  depends_on "python@3.12"
  depends_on "fzf"
  depends_on "git"

  def install
    py = Formula["python@3.12"].opt_bin/"python3.12"
    venv_python = libexec/"bin/python"
    # Create venv
    system py, "-m", "venv", libexec
    # Upgrade pip tooling
    system libexec/"bin/pip", "install", "--upgrade", "pip", "setuptools", "wheel"
    # Install this package into the venv
    system libexec/"bin/pip", "install", buildpath
    # Link the console script
    bin.install_symlink libexec/"bin/git-branches"

    # Generate shell completions via the Click CLI
    (bash_completion/"git-branches").write Utils.safe_popen_read(
      venv_python, "-m", "git_branch_list.cli", "completion", "--shell", "bash"
    )
    (zsh_completion/"_git-branches").write Utils.safe_popen_read(
      venv_python, "-m", "git_branch_list.cli", "completion", "--shell", "zsh"
    )
    (fish_completion/"git-branches.fish").write Utils.safe_popen_read(
      venv_python, "-m", "git_branch_list.cli", "completion", "--shell", "fish"
    )
  end

  test do
    help = shell_output("#{bin}/git-branches -h")
    assert_match "Interactive git branch viewer", help
  end
end
