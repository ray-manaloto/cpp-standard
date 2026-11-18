# shellcheck shell=sh
# The agents' keys in a project container (D155), read from the read-only mount at each shell start:
# CLAUDE_CODE_OAUTH_TOKEN for Claude Code and GEMINI_API_KEY for the Antigravity CLI (with modelProvider
# "gemini" in its settings, which agents:up sets). Sourced by login shells (/etc/profile.d) and by interactive
# ones (/etc/bash.bashrc).
if [ -s /run/agent-secrets/claude-oauth-token ]; then
  CLAUDE_CODE_OAUTH_TOKEN=$(cat /run/agent-secrets/claude-oauth-token)
  export CLAUDE_CODE_OAUTH_TOKEN
fi
if [ -s /run/agent-secrets/gemini-api-key ]; then
  GEMINI_API_KEY=$(cat /run/agent-secrets/gemini-api-key)
  export GEMINI_API_KEY
fi
