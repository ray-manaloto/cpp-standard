#!/usr/bin/env bash
# Setup step 6: create the cpp-standard-agents App from its manifest and
# store its private key in the login Keychain (docs/runbooks/agent-app.md).
# Run on the Mac host, once. It opens a page in the browser, waits for the
# owner to create the App, then exchanges the code and stores the key.
#
# The key never reaches a shell variable, a here-string, a file or a
# command line: the conversion response is piped into Python, which writes
# the Keychain command to security's stdin.
set -euo pipefail

item="cpp-standard-agent-app"
port=8765
cd "$(git rev-parse --show-toplevel)"
manifest="docs/runbooks/agent-app.manifest.json"

if security find-generic-password -s "$item" >/dev/null 2>&1; then
  echo "agent-app-create: Keychain item $item already exists" >&2
  exit 1
fi
if lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "agent-app-create: port $port is in use" >&2
  exit 1
fi

dir="$(mktemp -d)"
listener=""
cleanup() {
  [[ -n "$listener" ]] && kill "$listener" 2>/dev/null || true
  rm -rf "$dir"
}
trap cleanup EXIT
state="$(openssl rand -hex 16)"

# The form page: posts the manifest, with the state value, to the
# organization's new-App page.
python3 -I -c "$(
  cat <<'PY'
import html, json, sys
out, state, manifest = sys.argv[1:4]
m = json.dumps(json.load(open(manifest)))
open(out, "w").write(f"""<!doctype html><meta charset="utf-8"><title>Create agent App</title>
<form method="post" action="https://github.com/organizations/ray-manaloto/settings/apps/new?state={state}">
<input type="hidden" name="manifest" value="{html.escape(m, quote=True)}">
<button type="submit">Create the cpp-standard-agents App</button></form>""")
PY
)" "$dir/form.html" "$state" "$manifest"

# The listener: prints the code from the first request whose state matches,
# then exits. Requests with another state are refused.
python3 -I -c "$(
  cat <<'PY'
import http.server, sys, urllib.parse
want, port = sys.argv[1], int(sys.argv[2])
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        ok = q.get("state", [""])[0] == want and "code" in q
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Done. Return to the terminal." if ok else b"State mismatch.")
        if ok:
            print(q["code"][0], flush=True)
            self.server.done = True
    def log_message(self, *a): pass
s = http.server.HTTPServer(("127.0.0.1", port), H)
s.done = False
while not s.done:
    s.handle_request()
PY
)" "$state" "$port" >"$dir/code" &
listener=$!

for _ in $(seq 1 10); do
  lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 && break
  kill -0 "$listener" 2>/dev/null || {
    echo "agent-app-create: listener failed to start" >&2
    exit 1
  }
  read -r -t 1 </dev/zero || true
done

open "$dir/form.html"
echo "Waiting for the owner to create the App in the browser..."
wait "$listener"
listener=""

gh api -X POST "/app-manifests/$(cat "$dir/code")/conversions" |
  python3 -I -c "$(
    cat <<'PY'
import base64, json, sys
r = json.load(sys.stdin)
print(f"slug={r['slug']} id={r['id']} owner={r['owner']['login']}", file=sys.stderr)
key = base64.b64encode(r["pem"].encode()).decode()
print(f"add-generic-password -s {sys.argv[1]} -a {r['client_id']} -w {key}")
PY
  )" "$item" |
  security -i

if security find-generic-password -s "$item" >/dev/null 2>&1; then
  echo "stored the key in Keychain item $item"
else
  echo "agent-app-create: the Keychain item $item was not created" >&2
  exit 1
fi
