#!/usr/bin/env bash
# run-guard.sh - runs one of the keys guards and answers in the JSON form Claude and Codex obey.
#
#   bash run-guard.sh guard-keys.sh PreToolUse         before a shell command (Claude and Codex)
#   bash run-guard.sh guard-output.sh PostToolUse      after it (Claude and Codex)
#   bash run-guard.sh guard-prompt.sh UserPromptSubmit before a chat message is sent (Claude)
#
# Each guard says "stop" by exiting 2 with a message. That exit code does not survive the trip:
# on Windows, Claude starts hooks through PowerShell, which turns a 2 into a plain failure, and
# Codex counts exit 2 as a hook that failed. Either way the command ran anyway (both seen on
# Oct 10, Claude Code and Codex 0.161.0 on Windows). A JSON answer on stdout works everywhere:
# "deny" before a command, "block" after one or for a message.
#
# If the guard itself cannot run (missing, broken), this stops the command too, with a fixed
# message: a keys check that quietly does nothing is worse than one that is noisy.
#
# Plain bash with no outside programs, like the guards. Works with the bash 3.2 on a Mac.

guard=$1
event=$2
here=${BASH_SOURCE[0]%/*}
[[ $here == "${BASH_SOURCE[0]}" ]] && here=.
IFS= read -r -d '' input
message=$(printf '%s' "$input" | bash "$here/$guard" 2>&1 >/dev/null)
code=$?
[[ $code -eq 0 ]] && exit 0
if [[ $code -ne 2 ]]; then
    message="The keys check ($guard) could not run, so this was stopped to be safe. Tell the person in plain words that the keys check needs fixing (HELP.md, Keys), and do not try to get around it."
fi

bs='\'                          # quoted replacements behave the same in every bash version
message=${message//"$bs"/"$bs$bs"}
message=${message//\"/"$bs\""}
message=${message//$'\r'/}
message=${message//$'\n'/ }
message=${message//$'\t'/ }
if [[ $event == PreToolUse ]]; then
    printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}\n' "$message"
else
    printf '{"decision":"block","reason":"%s"}\n' "$message"
fi
exit 0
