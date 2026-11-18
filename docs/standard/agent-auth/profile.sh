# shellcheck shell=sh
# Claude Code's key in a project container (D155), read from the read-only mount at each shell start. Sourced by
# login shells (/etc/profile.d) and by interactive ones (/etc/bash.bashrc). The Antigravity CLI and Codex log in
# once per container instead; no agent ever runs agy (AGENTS.md).
if [ -s /run/agent-secrets/claude-oauth-token ]; then
  CLAUDE_CODE_OAUTH_TOKEN=$(cat /run/agent-secrets/claude-oauth-token)
  export CLAUDE_CODE_OAUTH_TOKEN
fi
