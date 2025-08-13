require "language/python/virtualenv"

class GitBranches < Formula
  include Language::Python::Virtualenv

  desc "Interactive Git branch browser with fzf and GitHub PR status"
  homepage "https://github.com/chmouel/git-branches"
  head "https://github.com/chmouel/git-branches.git", branch: "main"
  license "Apache-2.0"

  depends_on "python@3.12"
  depends_on "fzf"
  depends_on "git"

  def install
    virtualenv_install_with_resources
  end

  test do
    help = shell_output("#{bin}/git-branches -h")
    assert_match "Interactive git branch viewer", help
  end
end

