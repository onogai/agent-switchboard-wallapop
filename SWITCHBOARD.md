# HTTP and Switchboard deployment

The Python package, CLI and native stdio MCP remain independent. The HTTP image uses
Supergateway 4.2.2 with stateful Streamable HTTP and a mandatory key file.
Each legacy MCP session has its own child process; this does not promise a
persistent child across independent Gateway sessions.

## Standalone HTTP

Build `docker build -f packaging/http/Dockerfile -t wallapop-http .`.
Create a private state directory and a separate nonempty key file (mode 0600)
owned by your runtime UID. For local-only access:

```sh
docker run --rm --user "$(id -u):$(id -g)" --read-only \
  --tmpfs /tmp:rw,nosuid,noexec,size=128m --cap-drop ALL \
  --security-opt no-new-privileges:true \
  -p 127.0.0.1:8768:8768 \
  -v "$PWD/data:/data" -v "$PWD/mcptoken:/run/secrets/mcptoken:ro" wallapop-http
```

Use an existing Wallapop session in data/ or the native CLI login with
WALLAPOP_CONFIG_DIR pointed there. HTTP clients send Authorization: Bearer
with the separate MCP token. Do not expose a write-enabled MCP publicly.

## Switchboard

`./switchboard addon https://github.com/onogai/agent-switchboard-wallapop.git`

Schema v2 provisions the private network, state, MCP token and registration.
The add-on has no published port. Grant the desired tools in Manager.

## Replace the old production service

The 32-tool production saved-search implementation has been imported into this
repository. Before cutover verify the live catalog matches the candidate,
including list_saved_searches and saved_search_results.

The existing anonymous-to-bearer transition is not supported by the staged
replacement helper. Use a separate candidate instance for smoke tests, then
install under the final name wallapop after removing the old Registry source.
Keep the old container and state until successful verification. Pause Wallapop
monitoring and other callers during offline session transfer; do not refresh
one account's tokens concurrently from both copies.

1. Install the candidate with `--name wallapop-new --target production`.
2. Stop the candidate and the legacy container (do not remove either).
3. From the Switchboard host, run
   `python3 addons/wallapop-new/source/scripts/adopt_session.py --destination addons/wallapop-new/state/data`.
   Run as the state owner. The helper copies the legacy bind mount and imports
   effective credential environment variables without printing values. The
   add-on-generated MCP token is not copied or changed.
4. Start the candidate, grant only test reads, verify the local status, saved
   searches, search results, catalog and timing. No test writes to Wallapop.
5. Stop the candidate. Preserve its most recent state if tokens refreshed.
   Remove the old Registry source only when ready to recreate its grants.
   Install final instance wallapop, stop it and copy the tested data offline
   into its empty state/data, keeping its independently generated MCP token.
6. Start final instance, approve and restore required grants; refresh client
   catalogs and verify monitoring uses the original public tool names.
7. Remove the legacy service definition in Core only after success. Keep
   a private backup of its state. Rollback requires current Wallapop session
   state if token refresh changed it, not merely re-enabling the old endpoint.

Legacy packaging/homelab remains available until this production cutover is
verified, so rebuilding the old service is not silently changed.

## Saved-search monitoring

The local history is account-scoped in the existing persistent `/data` mount. Before enabling the scheduled task, run the diagnostic below in the updated add-on container, with other Wallapop callers paused. It reads real search pages, uses a temporary monitoring database, prints only aggregate timings and field counts (not tokens, listing contents or cursor values), then verifies replay without upstream calls.

```sh
python -m wallapop_mcp.benchmark_monitor
```

Use `--second-scan` for a second fresh scan. Gateway tool calls have a 60-second deadline in current Switchboard Core; compare full-scan wall time with that deadline, including session initialization overhead. For larger search sets, use explicit search_ids and stable per-selection run IDs, or raise the upstream deadline after measuring. Do not change the monitoring rule until the live scan is validated.
