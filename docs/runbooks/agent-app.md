# Runbook: create the agent App

Setup step 6 of the environment standard (D40, D52, D71, D100). Agents push,
open pull requests and dispatch workflows on `ray-manaloto/cpp-standard` as
the GitHub App `cpp-standard-agents`. Its private key stays in the Mac host's
login Keychain, and `mise run agent:token` turns it into one-hour tokens.

The agent runs every command here on the Mac host. The owner does two things
in the browser: create the App, then install it.

## Before you start

- `main` holds `.github/CODEOWNERS`, and
  `gh api repos/ray-manaloto/cpp-standard/codeowners/errors --jq '.errors | length'`
  prints `0`. The App must never exist on a `main` without it (D100).
- `gh auth status` shows the owner's login, an admin of the `ray-manaloto`
  organization.
- No Keychain item `cpp-standard-agent-app` exists yet:
  `security find-generic-password -s cpp-standard-agent-app` fails.

## The manifest

[`agent-app.manifest.json`](agent-app.manifest.json) sets:

| Field | Value | Why |
|---|---|---|
| `name` | `cpp-standard-agents` | The name the design uses |
| `public` | `false` | Only the `ray-manaloto` organization can install it |
| `hook_attributes.active` | `false` | No webhook; nothing receives events |
| `default_permissions` | contents, pull_requests, workflows and actions: `write` | Push, open PRs, edit workflows, dispatch and rerun workflows (D40). Metadata read is added by GitHub |
| `redirect_url` | `http://127.0.0.1:8765/` | A one-shot listener on the Mac host receives the code |

The App gets no administration, secrets or members permission, so it cannot
change the ruleset, read secrets or change who owns code.

## 1. Agent: start the creation script

```sh
docs/runbooks/agent-app-create.sh
```

[`agent-app-create.sh`](agent-app-create.sh) runs as one process, from the
repository root:

- It stops if the Keychain item already exists or port 8765 is in use.
- It writes a local form page that posts the manifest, with a random `state`
  value, to the organization's new-App page, and opens it in the browser.
- It starts a listener on `127.0.0.1:8765`. The listener refuses requests
  with another `state` value, takes the code from the first request that
  matches, and exits.
- It exchanges the code through `POST /app-manifests/{code}/conversions` and
  pipes the response into Python, which writes the Keychain command to
  `security -i` on stdin. The key never reaches a shell variable, a
  here-string, a file or a command line.
- It checks that the Keychain item exists and deletes its temporary
  directory.

The Keychain item's account is the App's client ID, and its password is the
base64 of the PEM key, which is what `agent:token` reads.

## 2. Owner: create the App

In the browser page that opened:

1. Click **Create the cpp-standard-agents App**.
2. On GitHub's page, check that the name is `cpp-standard-agents`, the owner
   is `ray-manaloto`, and the permissions are exactly the four above.
3. Click **Create GitHub App**. Confirm 2FA if GitHub asks.
4. The browser shows "Done. Return to the terminal."

The code is short-lived and works once; the script exchanges it at once.

## 3. Agent: check the script's output

It ends with `slug=cpp-standard-agents id=<number> owner=ray-manaloto` and
`stored the key in Keychain item cpp-standard-agent-app`.

## 4. Owner: install the App on cpp-standard only

1. Open <https://github.com/apps/cpp-standard-agents/installations/new>.
2. Choose the `ray-manaloto` organization.
3. Choose **Only select repositories**, pick `cpp-standard`, and click
   **Install**.

## 5. Agent: check it

```sh
mise run -q agent:token >/dev/null && echo minted
GH_TOKEN="$(mise run -q agent:token)" gh api /installation/repositories \
  --jq '[.repositories[].full_name]'
```

Done when:

- the first command prints `minted`;
- the second prints exactly `["ray-manaloto/cpp-standard"]`;
- a one-off App PR that touches `.github/CODEOWNERS` shows
  `mergeStateStatus` `BLOCKED` with `reviewDecision` `REVIEW_REQUIRED`. Close
  it without approving and delete its branch.

## Undo

- Delete the App: organization settings, **Developer settings**, **GitHub
  Apps**, `cpp-standard-agents`, **Delete GitHub App**. This also removes its
  installation.
- Delete the key: `security delete-generic-password -s cpp-standard-agent-app`.
- Delete the token cache: the `cpp-standard-agent-<uid>` directory under
  `$TMPDIR`.
