_git_branches_completion() {
    local cur prev words cword
    _get_comp_words_by_ref -n : cur prev words cword

    if [[ "$prev" == "-R" || "$prev" == "-D" ]]; then
        local remotes
        remotes=$(git remote)
        COMPREPLY=($(compgen -W "${remotes}" -- "$cur"))
        return 0
    fi

    if [[ "$cur" == -* ]]; then
        local opts="-r -R -d -D -s -n -S -C -l -h"
        # Basic mutual exclusion
        if [[ " ${words[*]} " =~ " -r " ]]; then
            opts=${opts//-R/}
        elif [[ " ${words[*]} " =~ " -R " ]]; then
            opts=${opts//-r/}
        fi
        if [[ " ${words[*]} " =~ " -d " ]]; then
            opts=${opts//-D/}
            opts=${opts//-r/}
            opts=${opts//-R/}
        elif [[ " ${words[*]} " =~ " -D " ]]; then
            opts=${opts//-d/}
            opts=${opts//-r/}
            opts=${opts//-R/}
        fi
        COMPREPLY=($(compgen -W "${opts}" -- "$cur"))
    fi
}

complete -F _git_branches_completion git-branches
