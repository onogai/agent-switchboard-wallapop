#!/usr/bin/env python3
"""Offline copy of a legacy Docker Wallapop session into an empty add-on state/data."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def read_json(path):
    if not path.exists():
        return {}
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} is not a JSON object")
    return value


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")
    path.chmod(0o600)


def adopt(source, target, env):
    if not source.is_dir() or not target.is_dir() or any(target.iterdir()):
        raise ValueError("Source must exist and destination must be an empty directory")
    if source.resolve() == target.resolve():
        raise ValueError("Source and destination must differ")
    # The files may contain live credentials: never print their contents.
    if any(p.is_symlink() or not p.is_file() for p in source.iterdir()):
        raise ValueError("Unexpected state entry; inspect and migrate it explicitly")
    with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
        staged = Path(tmp) / "data"
        staged.mkdir(mode=0o700)
        for p in source.iterdir():
            dest = staged / p.name
            shutil.copyfile(p, dest)
            dest.chmod(0o600)
        creds_path, session_path = staged / "credentials.json", staged / "session.json"
        creds, session = read_json(creds_path), read_json(session_path)
        browser = env.get("WALLAPOP_BROWSER_SESSION_TOKEN", "").strip()
        access = env.get("WALLAPOP_ACCESS_TOKEN", "").strip()
        if browser:
            # Match the legacy library's account-selection precedence.
            if session.get("__Secure-next-auth.session-token") != browser:
                creds, session = {}, {}
            session["__Secure-next-auth.session-token"] = browser
            for key, cookie in (("WALLAPOP_DEVICE_ID", "device_id"), ("WALLAPOP_DEVICE_FGP", "device_fgp")):
                if env.get(key, "").strip():
                    session[cookie] = env[key].strip()
            write_json(session_path, session)
            write_json(creds_path, creds)
        elif access:
            # Legacy explicit access-token mode ignores browser credentials.
            write_json(session_path, {})
            write_json(creds_path, {"access_token": access, "refresh_token": env.get("WALLAPOP_REFRESH_TOKEN", "")})
        if not (read_json(creds_path).get("access_token") or read_json(session_path).get("accessToken")
                or read_json(session_path).get("__Secure-next-auth.session-token")):
            raise ValueError("No stored Wallapop authorization found")
        os.replace(staged, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-container", default="switchboard-services-wallapop")
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        info = json.loads(subprocess.check_output(["docker", "inspect", args.legacy_container]))[0]
        if info["State"]["Running"]:
            raise ValueError("Stop the legacy container before migrating")
        mount = next(m for m in info["Mounts"] if m["Destination"] == "/data" and m["Type"] == "bind")
        env = dict(entry.split("=", 1) for entry in info["Config"]["Env"] if "=" in entry)
        adopt(Path(mount["Source"]), args.destination, env)
    except (OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError) as exc:
        # JSON errors and Docker output can contain private details.
        print(f"Session migration failed ({type(exc).__name__}); no credentials printed", file=__import__("sys").stderr)
        return 1
    print("Wallapop state copied; legacy state and MCP bearer token unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
