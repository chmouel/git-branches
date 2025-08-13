# fish completion for git-branches

# Short flags
complete -c git-branches -s r -d 'Browse remote branches (interactive)'
complete -c git-branches -s R -d 'Browse specific remote' -a '(git remote 2>/dev/null)'
complete -c git-branches -s d -d 'Delete local branches (multi-select)'
complete -c git-branches -s D -d 'Delete remote branches (multi-select)' -a '(git remote 2>/dev/null)'
complete -c git-branches -s s -d 'Show pushed status (exists on remote)'
complete -c git-branches -s n -d 'Limit to first NUM branches' -r
complete -c git-branches -s S -d 'With -s, show all branches'
complete -c git-branches -s C -d 'Disable colors'
complete -c git-branches -s l -d 'List mode only (no checkout)'
complete -c git-branches -s h -l help -d 'Show help'

# Long flags
complete -c git-branches -l refresh -d 'Force refresh PR cache (ignore ETag)'
complete -c git-branches -l checks -d 'Fetch and show GitHub Actions status'

