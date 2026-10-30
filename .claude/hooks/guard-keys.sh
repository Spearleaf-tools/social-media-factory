#!/usr/bin/env bash
# guard-keys.sh - stops a shell command that would show a key, before it runs.
#
# Claude runs this before every shell command (the Bash and PowerShell tools; see
# .claude/settings.json). It reads the request on stdin and exits 2 to block it.
#
# Why it exists: settings.json already stops Claude's own file tools from opening keys.env,
# but a shell command (cat keys.env, a Python one-liner, printing the environment) went
# around that, and only the written rule in CLAUDE.md stood in the way.
#
# Honest limits: this is a word check, so it stops accidents and plain attempts, not a
# determined trick. The Social Media Factory still has to read keys.env to work, and nothing here
# changes that. keys.py keeps its own promise never to print a key. Known ways past it, written
# down on purpose: building the file name from pieces at run time ($p='ke'+'ys.env'), a script
# file that reads the keys and is then run, copying or zipping the folder, and Python started in
# ways this check does not recognise. guard-output.sh is the second line: it notices a key that
# shows up in a command's output anyway.
#
# ChatGPT (Codex) runs this same file before its shell commands (see .codex/config.toml).
#
# Plain bash with no outside programs: it runs before every command, and on Windows each
# extra program costs about half a second. Works with the bash 3.2 that ships on a Mac.
# .gitattributes keeps this file's line endings plain, because a hook that cannot run lets
# the command through.

IFS= read -r -d '' input
shopt -s nocasematch
set -f      # never expand a * from the command against real files here

# The command itself, still JSON-escaped. Fall back to the whole request if it can't be found.
re_cmd='"command"[[:space:]]*:[[:space:]]*"(([^"\\]|\\.)*)"'
if [[ $input =~ $re_cmd ]]; then cmd=${BASH_REMATCH[1]}; else cmd=$input; fi

# The one thing people need: opening keys.env in their own editor to paste a key in, exactly
# as the setup workflow says (on a Mac `open -t keys.env`, on Windows `notepad keys.env`).
# Nothing else may ride along, so no ; & | < > $ or backticks.
re_editor='^[[:space:]]*(open -t|notepad(\.exe)?)[[:space:]]+(\\")?[^";&|<>$`]*keys\.env(\\")?[[:space:]]*$'
[[ $cmd =~ $re_editor ]] && exit 0

# The example files hold no keys, so mentioning them is fine.
check=${cmd//keys.env.example/}
check=${check//.env.example/}

block() {
    echo "Blocked to keep keys private: $1. Never read, print or search keys.env, .env files or" \
         "the environment. To see which keys are set, run factory.py status. To add a key, open" \
         "keys.env in the person's editor (Mac: open -t keys.env, Windows: notepad keys.env) and" \
         "let them paste it." >&2
    exit 2
}

re='keys\.env';                                         [[ $check =~ $re ]] && block "this command names keys.env"
re='(^|[^[:alnum:]_])\.env([^[:alnum:]_]|$)';           [[ $check =~ $re ]] && block "this command names a .env file"
re='printenv|/proc/[^[:space:]]*/environ';              [[ $check =~ $re ]] && block "this command prints the environment"
re='(^|[;&|(`[:space:]])(env|set|export -p|declare -[a-z]*[px][a-z]*)[[:space:]]*($|[;&|)`])'
                                                        [[ $check =~ $re ]] && block "this command prints the environment"
re='(get-childitem|gci|ls|dir|get-item)[[:space:]]+env:'; [[ $check =~ $re ]] && block "this command lists the environment"
re='getenvironmentvariable|os\.environ|os\.getenv|process\.env'
                                                        [[ $check =~ $re ]] && block "this command reads the environment"
re='(\$|%|env:)\{?(METRICOOL_USER_TOKEN|METRICOOL_USER_ID|ELEVENLABS_API_KEY|APIFY_API_TOKEN)'
                                                        [[ $check =~ $re ]] && block "this command reads a key"
re='doppler[[:space:]]+(secrets|run|download)';         [[ $check =~ $re ]] && block "this command reads keys from Doppler"

# --- The Social Media Factory's own key reader, from Python started on the command line. factory.py itself
# never needs it spelled out, so a one-liner that names it is reaching for the keys.
re_py='(^|[^[:alnum:]_])(i?python[0-9.]*|py)(\.exe)?[[:space:]]+(-[[:alpha:]]*c|-([[:space:]]|$)|<<)|<<'
re='smf\.keys|from[[:space:]]+smf[[:space:]]+import[^;|&]*keys|parse_env_file|KEYS_FILE'
[[ $check =~ $re_py && $check =~ $re ]] && block "this command uses the Social Media Factory's key reader"

# --- Wildcards and brace patterns that could pick a keys file without spelling its name
# (cat keys.e*, type .\k*.env, cat ke{ys,x}.e{nv,xt}). A {a,b} group is treated as "anything",
# so nothing is ever expanded here. A word with no wildcard is left to the checks above.
# The keys files a pattern must not be able to pick: the usual names, plus every .env.* file
# that really is in the folder (so .env.staging counts too).
keyfiles="keys.env .env .env.local .env.production .env.development .env.staging .env.test"
set +f
for file in "${CLAUDE_PROJECT_DIR:-$PWD}"/.env.*; do
    [[ -f $file && $file != *.example ]] && keyfiles="$keyfiles ${file##*/}"
done
set -f
# Quoted text is never turned into file names by bash, and it is often program text or a search
# pattern (python -c "print(2 * 3)", rg '.*' smf), so it is set aside, except in a command that
# expands wildcards even in quotes (PowerShell's Get-Content and kin). Decided per command, so in
# rg '.*' smf | cat the quoted pattern still belongs to rg. `unq` is the command with every quoted
# character turned into a space (same length, so a position means the same in both).
unq=""
q=""
n=${#check}
[[ $n -gt 4000 ]] && unq=$check            # very long: keep the quotes, which only checks more
# The command is still JSON-escaped here: a shell backslash is \\ and a shell " is \", so the
# shell's own \" is \\\". An escaped character is never a quote.
i=0
while [[ $n -le 4000 && $i -lt $n ]]; do
    c=${check:i:1}
    two=${check:i:2}
    four=${check:i:4}
    if [[ -z $q ]]; then
        if [[ $four == '\\\"' || $four == '\\\\' ]]; then unq="$unq    "; i=$((i + 4)); continue
        elif [[ $two == '\\' ]]; then unq="$unq  ${check:i+2:1}"; i=$((i + 3)); continue
        elif [[ $c == "'" ]]; then q=s; unq="$unq "
        elif [[ $two == '\"' ]]; then q=d; unq="$unq  "; i=$((i + 1))
        else unq="$unq$c"; fi
    elif [[ $q == s ]]; then
        [[ $c == "'" ]] && q=""
        unq="$unq "
    else
        if [[ $four == '\\\"' || $four == '\\\\' ]]; then unq="$unq    "; i=$((i + 4)); continue
        elif [[ $two == '\"' ]]; then q=""; unq="$unq  "; i=$((i + 1))
        elif [[ $two == '\\' ]]; then unq="$unq  "; i=$((i + 1))
        else unq="$unq "; fi
    fi
    i=$((i + 1))
done
re_ps_files='^[[:space:]]*(get-content|gc|type|cat|copy-item|cp|move-item|mv|select-string|sls|get-item|gi|import-csv|more)([[:space:]]|$)'
pat=""
start=0
i=0
while [[ $i -le $n ]]; do
    c=${unq:i:1}
    if [[ $i -eq $n || $c == ";" || $c == "|" || $c == "&" ]]; then
        len=$((i - start))
        part=${unq:start:len}
        # The command's name is read with its quotes taken off (PowerShell: & 'Get-Content' ...).
        raw=${check:start:len}
        raw=${raw//[\'\"\\]/}
        [[ $raw =~ $re_ps_files ]] && part=${check:start:len}
        pat="$pat $part"
        start=$((i + 1))
    fi
    i=$((i + 1))
done
# A pattern that only leaves files OUT of a search (--exclude=*env*) is not picking one.
re_exclude='--exclude(-dir)?=[^[:space:]]*'
while [[ $pat =~ $re_exclude ]]; do pat=${pat/"${BASH_REMATCH[0]}"/ }; done
re_brace='\{[^{}]*\}'
while [[ $pat =~ $re_brace ]]; do pat=${pat/"${BASH_REMATCH[0]}"/*}; done
pat=${pat//\\\"/ }
pat=${pat//[\"\'\`;|&<>()=,]/ }
for word in $pat; do
    case $word in *\**|*\?*|*\[*) ;; *) continue ;; esac
    base=${word//\\//}
    base=${base##*/}
    [[ -n $base ]] || continue
    for name in $keyfiles; do
        # shellcheck disable=SC2053  # the right-hand side is a pattern on purpose
        [[ $name == $base ]] && block "a wildcard in this command could pick out a keys file ($word)"
    done
done

# --- Searching the whole folder: a recursive search with no folder named, or aimed at the
# folder itself, reads keys.env too. Naming the folders to search (smf tests) is fine. rg skips
# keys files by itself (they are git-ignored) unless told not to; git grep only reads tracked
# files unless told otherwise.
broad() {   # $1 = a search target; true when it means "this whole folder" or more
    local t=${1//\\//}
    while [[ $t == *//* ]]; do t=${t//\/\///}; done
    while [[ $t == ?*/ ]]; do t=${t%/}; done
    case $t in
        .|..|../*|*/..|~*|/*|[A-Za-z]:*|\$*|\*) return 0 ;;
    esac
    return 1
}
excluded() {   # the command itself leaves keys files out of the search
    local x
    for x in $seg; do
        x=${x//\\\"/}; x=${x//[\"\']/}
        case $x in --exclude=*) ;; *) continue ;; esac
        x=${x#*=}
        [[ keys.env == $x && .env == $x ]] && return 0
    done
    return 1
}
search_block() {
    block "this searches the whole folder, keys files included. Name the folders to search instead, for example: rg <word> smf tests"
}
segs=${check//[;&|]/$'\n'}
recursive_listing=""
re_list='(^|[[:space:]])(get-childitem|gci|dir|ls)[[:space:]]'
re_rec='(^|[[:space:]])-(r|recurse|s)([[:space:]]|$)'
re_sls='(^|[[:space:]])(select-string|sls)([[:space:]]|$)'
if [[ $check =~ $re_sls ]]; then
    while IFS= read -r seg; do
        if [[ " $seg " =~ $re_list && " $seg " =~ $re_rec ]]; then
            recursive_listing=1
            targets=()
            skip=""
            for w in $seg; do
                w=${w//\\\"/}; w=${w//[\"\']/}
                if [[ -n $skip ]]; then skip=""; [[ $prev == -path || $prev == -literalpath ]] && targets+=("$w"); continue; fi
                case $w in
                    get-childitem|gci|dir|ls) ;;
                    -path|-literalpath|-filter|-include|-exclude|-depth) skip=1; prev=$w ;;
                    -*) ;;
                    *) targets+=("$w") ;;
                esac
            done
            [[ ${#targets[@]} -eq 0 ]] && search_block
            for w in "${targets[@]}"; do broad "$w" && search_block; done
        fi
    done <<< "$segs"
fi
while IFS= read -r seg; do
    words=()
    for w in $seg; do w=${w//\\\"/}; w=${w//[\"\']/}; words+=("$w"); done
    [[ ${#words[@]} -gt 0 ]] || continue
    # Words that only start another command (command grep, sudo grep, xargs grep, NAME=value grep).
    while [[ ${#words[@]} -gt 1 ]]; do
        case ${words[0]##*/} in
            command|builtin|exec|time|nice|nohup|sudo|doas|xargs|*=*) words=("${words[@]:1}") ;;
            *) break ;;
        esac
    done
    verb=${words[0]##*/}
    verb=${verb%.exe}
    if [[ $verb == git && ${words[1]} == grep ]]; then
        verb="git grep"; words=("${words[@]:1}")
    fi
    recursive=""
    case $verb in
        grep|egrep|fgrep|zgrep)
            for w in "${words[@]:1}"; do
                case $w in --recursive|--dereference-recursive|-d) recursive=1 ;; --*) ;; -*[rR]*) recursive=1 ;; esac
            done ;;
        ack|ack-grep) recursive=1 ;;
        rg)
            for w in "${words[@]:1}"; do
                case $w in --no-ignore*|-u|-uu|-uuu|--unrestricted) recursive=1 ;; esac
            done ;;
        findstr)
            for w in "${words[@]:1}"; do case $w in /s|/S) recursive=1 ;; esac; done ;;
        "git grep")
            for w in "${words[@]:1}"; do case $w in --no-index|--untracked) recursive=1 ;; esac; done ;;
    esac
    [[ -n $recursive ]] || continue
    excluded && continue
    # The first plain word is what to look for (unless -e or -f gave it); the rest are where.
    targets=()
    have_pattern=""
    skip=""
    for w in "${words[@]:1}"; do
        if [[ -n $skip ]]; then skip=""; continue; fi
        case $w in
            -e|-f|--regexp|--file) have_pattern=1; skip=1 ;;
            -m|-A|-B|-C|-d|-D|-g|-t|-T|-j|--glob|--iglob|--type|--type-not|--max-count|--max-depth|--threads|            --exclude|--exclude-dir|--include|--context|--after-context|--before-context|--label|            --binary-files|--devices|--directories) skip=1 ;;
            -*|/*) [[ $verb == findstr ]] || [[ $w == -* ]] || targets+=("$w") ;;
            *) if [[ -z $have_pattern ]]; then have_pattern=1; else targets+=("$w"); fi ;;
        esac
    done
    [[ ${#targets[@]} -eq 0 ]] && search_block
    for w in "${targets[@]}"; do broad "$w" && search_block; done
done <<< "$segs"

exit 0
