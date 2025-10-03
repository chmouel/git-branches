# function to install in your ${fpath} function path.
# See zshcompsys(1) for details.
#
# redefine this variable for your environment
local worktree_dir=${GIT_BRANCHES_WORKTREE_BASEDIR:-$HOME/git/pac/trees}
local main_worktree=${worktree_dir}/main
local path_file="/tmp/.git-branches-path"

function __git_branch() {
    last_arg=${@: -1}
    if [[ -n ${last_arg} && -e ${worktree_dir}/${last_arg} ]];then
        cd ${worktree_dir}/${last_arg}
        return
    fi
    if ! git rev-parse --is-inside-work-tree &>/dev/null && test -d ${main_worktree}; then
        args=(--directory "${main_worktree}" "$@")
    fi
    trap 'rm -f ${path_file}' EXIT
    rm -f ${path_file} 2>/dev/null
    (( $+commands[git-branches] )) ||{
        echo "command git-branches is not found"
        return 1
    }
    $commands[git-branches] ${args[@]} $@
    if test -s ${path_file}; then
        output="${(f)$(<"$path_file")}"
        [[ -d ${output} ]] && {
            cd ${output}
            return
        }
        cat ${output}
    fi
}

__git_branch "$@"
# vim: ft=zsh
