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
    # Create venv
    system py, "-m", "venv", libexec
    # Upgrade pip tooling
    system libexec/"bin/pip", "install", "--upgrade", "pip", "setuptools", "wheel"
    # Install this package into the venv
    system libexec/"bin/pip", "install", buildpath
    # Link the console script
    bin.install_symlink libexec/"bin/git-branches"
  end

  test do
    help = shell_output("#{bin}/git-branches -h")
    assert_match "Interactive git branch viewer", help
  end
end
