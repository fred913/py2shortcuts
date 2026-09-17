# macOS signing service

This service must run as the logged-in macOS user whose `shortcuts sign` command works.
It listens on `127.0.0.1:8765`; expose it through an SSH tunnel or an authenticated TLS
reverse proxy. Do not bind it directly to a public interface.

Before installation, verify the actual signing path:

```sh
command -v shortcuts
shortcuts --version
shortcuts sign --mode anyone --input test.wflow --output test.shortcut
```

The launchd plist is a template. Replace `__PYTHON__`, `__SERVER__`, `__TOKEN_FILE__`,
and `__LOG_DIR__`, copy it to `~/Library/LaunchAgents/io.shengfan.py2shortcuts-signer.plist`,
then load it:

```sh
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/io.shengfan.py2shortcuts-signer.plist
launchctl kickstart -k gui/$(id -u)/io.shengfan.py2shortcuts-signer
curl http://127.0.0.1:8765/health
```

Sign an XML or binary workflow plist:

```sh
curl --fail-with-body \
  -H "Authorization: Bearer $PY2SHORTCUTS_SIGNING_TOKEN" \
  -H "Content-Type: application/x-plist" \
  --data-binary @workflow.plist \
  http://127.0.0.1:8765/v1/sign \
  --output workflow.shortcut
```
