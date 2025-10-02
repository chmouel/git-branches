# function to install in your ${fpath} function path.
# See zshcompsys(1) for details.
#
# redefine this variable for your environment
local worktree_dir=${GB_BASEDIR:-$HOME/git/pac/trees}

function __git_branch() {
    last_arg=${@: -1}
    if [[ -n ${last_arg} && -e ${worktree_dir}/${last_arg} ]];then
        cd ${worktree_dir}/${last_arg}
        return
    fi
    tmpfile=$(mktemp)
    tmpfile2=$(mktemp)
    trap 'rm -f "$tmpfile" "$tmpfile2"' EXIT

    (( $+commands[git-branches] )) ||{
        echo "command git-branches is not found"
        return 1
    }
    output=$($commands[git-branches] $@ >${tmpfile} 2>${tmpfile2}; echo $?)
    if test -s ${tmpfile}; then
        output="${(f)$(<"$tmpfile")}"
        [[ -d ${output} ]] && {
            cd ${output}
            return
        }
        cat ${output}
    elif test -s ${tmpfile2}; then
        cat ${tmpfile2} >&2
    fi
}

__git_branch "$@"
# vim: ft=zsh
