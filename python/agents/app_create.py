"""agents:app-create (.mise/tasks/agents/app-create): create the agents GitHub App and store its key (D155).

# GitHub's App-manifest flow (docs.github.com, "Registering a GitHub App from a manifest"), shaped like
# gh-aw's `bootstrap` (pkg/cli/bootstrap_profile_github_app.go, v1.2.2). No maintained CLI stores the key
# anywhere but a repository's Actions secrets, so this short helper does it:
#   1. serves a pre-filled manifest form on 127.0.0.1 and opens it; the owner clicks Create;
#   2. catches GitHub's redirect, checks its state, exchanges the one-time code
#      (POST /app-manifests/{code}/conversions, which needs no token);
#   3. pipes the private key straight into `mise run secret:set AGENTS_APP_PRIVATE_KEY` on stdin and the
#      client ID into AGENTS_APP_CLIENT_ID; the key is never printed, logged or written to a file, and the
#      client secret and webhook secret in the answer are dropped;
#   4. sends the browser to the App's install page, where the owner picks "All repositories" and clicks
#      Install, then waits for that installation and prints what it covers.
# Permissions: contents write, pull requests write, metadata read. No workflows, no webhook, private.
"""

import html
import http.server
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import webbrowser

NAME = os.environ.get("usage_name") or "ray-manaloto-agents"
KEY_NAME, ID_NAME = "AGENTS_APP_PRIVATE_KEY", "AGENTS_APP_CLIENT_ID"
HOME = os.path.expanduser("~")


def doppler_names() -> str:
    out = subprocess.run(
        ["mise", "run", "-q", "secret:list"],
        cwd=HOME,
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        sys.exit(
            "agents:app-create: cannot list the Doppler names (mise run secret:list)"
        )
    return out.stdout


def store(name: str, value: str) -> None:
    # secret:set reads the value from stdin and prints only "stored NAME".
    run = subprocess.run(
        ["mise", "run", "-q", "secret:set", name],
        cwd=HOME,
        input=value,
        text=True,
        capture_output=True,
        check=False,
    )
    if run.returncode != 0:
        sys.exit(
            f"agents:app-create: storing {name} in Doppler failed (exit {run.returncode})"
        )
    print(f"agents:app-create: stored {name} in Doppler")


names = doppler_names()
for n in (KEY_NAME, ID_NAME):
    if f" {n} " in names:
        sys.exit(
            f"agents:app-create: Doppler already has {n}; the App seems to exist. Stopping before GitHub."
        )

state = secrets.token_urlsafe(24)
result: dict = {}


class Handler(http.server.BaseHTTPRequestHandler):
    # No request log: the callback URL carries the one-time code.
    def log_message(self, format: str, *args: object) -> None:
        pass

    def reply(self, status: int, body: str, location: str | None = None) -> None:
        self.send_response(status)
        if location:
            self.send_header("Location", location)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body.encode())

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        port = PORT
        if url.path == "/":
            manifest = {
                "name": NAME,
                "url": "https://github.com/ray-manaloto",
                "description": "Short-lived tokens for agents in project containers (cpp-standard D155).",
                "hook_attributes": {
                    "url": "https://github.com/ray-manaloto",
                    "active": False,
                },
                "redirect_url": f"http://127.0.0.1:{port}/callback",
                "public": False,
                "request_oauth_on_install": False,
                "default_permissions": {
                    "contents": "write",
                    "pull_requests": "write",
                    "metadata": "read",
                },
                "default_events": [],
            }
            action = "https://github.com/settings/apps/new?state=" + urllib.parse.quote(
                state
            )
            self.reply(
                200,
                (
                    "<!doctype html><meta charset=utf-8><title>Create the agents App</title>"
                    f'<form method=post action="{html.escape(action)}">'
                    f'<input type=hidden name=manifest value="{html.escape(json.dumps(manifest))}">'
                    f"<p>Creating GitHub App <b>{html.escape(NAME)}</b>: contents write, pull requests write, "
                    "metadata read; no webhook; private.</p><button type=submit>Continue to GitHub</button></form>"
                    "<script>document.forms[0].submit()</script>"
                ),
            )
            return
        if url.path != "/callback" or result:
            self.reply(404, "not found")
            return
        q = urllib.parse.parse_qs(url.query)
        code, got_state = q.get("code", [""])[0], q.get("state", [""])[0]
        if not secrets.compare_digest(got_state, state) or not code.isalnum():
            self.reply(400, "state mismatch or bad code; nothing was stored")
            result["error"] = "state mismatch or bad code"
            return
        req = urllib.request.Request(
            f"https://api.github.com/app-manifests/{code}/conversions",
            method="POST",
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                app = json.load(resp)
        except (
            OSError,
            ValueError,
        ) as e:  # urllib and JSON errors; the message never holds the answer's body
            self.reply(502, "the code exchange failed; nothing was stored")
            result["error"] = f"code exchange failed: {type(e).__name__}"
            return
        pem, client_id, slug = (
            app.pop("pem", ""),
            str(app.get("client_id", "")),
            str(app.get("slug", "")),
        )
        app.clear()  # drops client_secret and webhook_secret
        if not pem.startswith("-----BEGIN") or not client_id or not slug:
            self.reply(
                502,
                "GitHub's answer lacked the key, client ID or slug; nothing was stored",
            )
            result["error"] = "incomplete answer"
            return
        store(KEY_NAME, pem)
        del pem
        store(ID_NAME, client_id)
        result.update(slug=slug, client_id=client_id)
        self.reply(
            302, "", location=f"https://github.com/apps/{slug}/installations/new"
        )


server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
PORT = server.socket.getsockname()[1]
start = f"http://127.0.0.1:{PORT}/"
print(
    f"agents:app-create: opening {start} - click Create on GitHub, then pick All repositories and Install"
)
webbrowser.open(start)
server.timeout = 5
deadline = time.time() + 30 * 60
while not result and time.time() < deadline:
    server.handle_request()
server.server_close()
if "error" in result or not result:
    sys.exit(f"agents:app-create: {result.get('error', 'timed out after 30 minutes')}")
print(
    f"agents:app-create: App {result['slug']} created, client ID {result['client_id']}"
)

# Wait for the owner's Install click; /user/installations lists the Apps installed on the owner's account.
for _ in range(120):
    jq = f'.installations[] | select(.app_slug == "{result["slug"]}") | .repository_selection'
    out = subprocess.run(
        ["gh", "api", "/user/installations", "--paginate", "--jq", jq],
        capture_output=True,
        text=True,
        check=False,
    )
    sel = out.stdout.strip()
    if sel:
        print(f"agents:app-create: installed, repository selection: {sel}")
        if sel != "all":
            print(
                "agents:app-create: pick All repositories in the App's installation settings",
                file=sys.stderr,
            )
            sys.exit(1)
        sys.exit(0)
    time.sleep(5)
sys.exit(
    "agents:app-create: no installation seen after 10 minutes; install it at "
    f"https://github.com/apps/{result['slug']}/installations/new"
)
