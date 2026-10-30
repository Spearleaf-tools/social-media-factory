#!/usr/bin/env bash
# guard-prompt.sh - stops a message that holds a key before it is sent to Claude.
#
# Claude runs this on every message the person sends (UserPromptSubmit; see
# .claude/settings.json). Exit 2 blocks the message: it never reaches Claude, and the reason
# below is shown to the person only.
#
# Why it exists: a key pasted into the chat by mistake has already left the computer, and the
# only fix is to replace it at the service, which takes time. This catches it first.
#
# Honest limits: it recognises keys and tokens (known beginnings, long random strings, a
# NAME=value line from keys.env). An ordinary password ("Fluffy2024") looks like normal words
# and cannot be told apart reliably, so the rule "keys go in keys.env, never in the chat" still
# matters.
#
# Plain bash with no outside programs, like guard-keys.sh, so it is quick on Windows too.

IFS= read -r -d '' input

# The message itself, still JSON-escaped. Fall back to the whole request if it can't be found.
re_prompt='"prompt"[[:space:]]*:[[:space:]]*"(([^"\\]|\\.)*)"'
if [[ $input =~ $re_prompt ]]; then msg=${BASH_REMATCH[1]}; else msg=$input; fi

block() {
    echo "Not sent: $1. Keys and passwords never go in the chat. To add a key, say" \
         "\"open my keys file\" and paste it there yourself. If this was a false alarm, send the" \
         "message again without the long code." >&2
    exit 2
}

# Keys that announce themselves by how they begin.
re='apify_api_[A-Za-z0-9]{20,}|sk_[A-Za-z0-9]{30,}|sk-ant-[A-Za-z0-9_-]{20,}|sk-(proj-)?[A-Za-z0-9_-]{30,}'
[[ $msg =~ $re ]] && block "it looks like it holds a service key"
re='gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}'
[[ $msg =~ $re ]] && block "it looks like it holds an access token"
re='-----BEGIN[A-Z ]*PRIVATE KEY-----'
[[ $msg =~ $re ]] && block "it holds a private key"

shopt -s nocasematch
# A line copied from keys.env, or a password written out.
re='(METRICOOL_USER_TOKEN|ELEVENLABS_API_KEY|APIFY_API_TOKEN|[A-Z_]*(SECRET|TOKEN|API_KEY))[[:space:]]*[=:][[:space:]]*[^[:space:]\\]{8,}'
[[ $msg =~ $re ]] && block "it looks like a line from a keys file"
re='(password|passwd|passcode)[[:space:]]*[:=][[:space:]]*[^[:space:]\\]{4,}'
[[ $msg =~ $re ]] && block "it looks like it holds a password"
shopt -u nocasematch

# A long random-looking string: 32+ letters, digits, - or _, mixing capitals, small letters and
# digits. Commit ids, colours and the like use small letters only, so they pass.
rest=$msg
re='[A-Za-z0-9_-]{32,}'
while [[ $rest =~ $re ]]; do
    tok=${BASH_REMATCH[0]}
    if [[ $tok =~ [[:upper:]] && $tok =~ [[:lower:]] && $tok =~ [[:digit:]] ]]; then
        block "it holds a long code that looks like a key or token"
    fi
    rest=${rest#*"$tok"}
done

exit 0
