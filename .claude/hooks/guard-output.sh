#!/usr/bin/env bash
# guard-output.sh - notices a key that shows up in a command's output anyway.
#
# Claude runs this after every shell command and file search (PostToolUse; see
# .claude/settings.json), and ChatGPT (Codex) after every shell command (.codex/config.toml).
# guard-keys.sh tries to stop a command that would show a key BEFORE it runs; this is the second
# line, for the ways around that check.
#
# It reads the key values itself (this is a program, not the AI) from keys.env, .env and .env.*
# in the project, plus the Social Media Factory's four known keys if they are set in its own environment, and
# looks for each one in what the command returned. If one is there it exits 2 with a message
# that names the key's line, never its value: the AI is told not to repeat or use it, and to
# tell the person which key to replace.
#
# Honest limits, written down on purpose:
# - It only sees the output it is given. Claude can cut very long output short before a hook
#   sees it, so a key past that point can be missed.
# - Claude has already seen the output when this runs; the message can only warn. Codex
#   replaces the result with this message instead, so there the key never reaches ChatGPT.
# - An encoded (base64, hex), split or partial copy of a key is not recognised.
# - Codex: text typed into a command that is still running (write_stdin) is not checked.
# - Keys that live only in Doppler are fetched inside the Social Media Factory's own process and are not known
#   here.
# - Values shorter than 8 characters are skipped (METRICOOL_USER_ID is a plain account number),
#   so they cannot cause false alarms on ordinary numbers.
#
# Plain bash with no outside programs, like guard-keys.sh, so it is quick on Windows and works
# with the bash 3.2 that ships on a Mac. It never prints, logs or saves a key.

IFS= read -r -d '' input
set -f
dir=${CLAUDE_PROJECT_DIR:-$PWD}
found=""
names=""

about() {   # plain words for a key's line
    case $1 in
        METRICOOL_USER_TOKEN|METRICOOL_USER_ID) echo "Metricool (posting and scheduling)" ;;
        ELEVENLABS_API_KEY) echo "ElevenLabs (transcribing recordings)" ;;
        APIFY_API_TOKEN) echo "Apify (research)" ;;
        *) echo "the $1 line" ;;
    esac
}

look_for() {   # $1 = the key's name, $2 = its value
    local value=$2 escaped
    [[ ${#value} -ge 8 ]] || return 0
    # The request is JSON, where a " or \ inside the output is written \" or \\ (and some
    # programs write / as \/), so the value is looked for both as it is and written that way.
    local bs='\'                # quoted replacements behave the same in every bash version
    escaped=${value//"$bs"/"$bs$bs"}
    escaped=${escaped//\"/"$bs\""}
    case $input in
        *"$value"*|*"$escaped"*|*"${escaped//\//"$bs/"}"*)
            found=1; case " $names " in *" $1 "*) ;; *) names="$names $1" ;; esac ;;
    esac
}

set +f              # the .env.* files must really be found
shopt -s nullglob
for file in "$dir/keys.env" "$dir/.env" "$dir"/.env.*; do
    case $file in *.example) continue ;; esac
    [[ -f $file ]] || continue
    if ! [[ -r $file ]] || ! { : < "$file"; } 2>/dev/null; then
        # A keys file this check cannot read means it cannot tell whether a key is in the output.
        echo "The keys check could not read ${file##*/}, so it cannot tell whether that output holds a key." >&2
        exit 3
    fi
    first=1
    while IFS= read -r line || [[ -n $line ]]; do
        line=${line%$'\r'}
        if [[ -n $first ]]; then line=${line#$'\xef\xbb\xbf'}; first=""; fi
        re='^[[:space:]]*([Ee][Xx][Pp][Oo][Rr][Tt][[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=[[:space:]]*(.*)$'
        [[ $line =~ $re ]] || continue
        name=${BASH_REMATCH[2]}
        value=${BASH_REMATCH[3]}
        while [[ $value == *[[:space:]] ]]; do value=${value%?}; done
        if [[ ${#value} -ge 2 && ( ( $value == \"*\" ) || ( $value == \'*\' ) ) ]]; then
            value=${value:1:${#value}-2}
        fi
        look_for "$name" "$value"
    done < "$file"
done
shopt -u nullglob
set -f

for name in METRICOOL_USER_TOKEN METRICOOL_USER_ID ELEVENLABS_API_KEY APIFY_API_TOKEN; do
    look_for "$name" "${!name}"
done

[[ -n $found ]] || exit 0

services=""
for name in $names; do services="$services; $(about "$name")"; done
services=${services#; }
echo "Stop: a key appeared in that output (from: $services). Do not repeat, quote, summarise," \
     "save or use it, and do not run that command again. Tell the person plainly: \"A key showed" \
     "up in my output: $services. Please replace it now (HELP.md, section 'Replace a key').\"" >&2
exit 2
