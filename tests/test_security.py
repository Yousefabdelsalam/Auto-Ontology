"""Security checks. No token, no LLM calls. Secret VALUES are never printed - only variable names.

1. Ports 3000/3001/3002/5432 (and 3003 if the MCP server runs) listen on 127.0.0.1 only, per netstat and per Docker.
2. Those ports are refused on this PC's other (LAN / virtual) IP addresses.
3. No default or example password/secret is still in .env or in the running containers' environment.
4. KumoRFM (uploads tables to an outside service) is disabled.
5. pgAdmin is not running; .env is ignored by the repo's .gitignore.
"""
from __future__ import annotations

import json
import re
import socket
import subprocess

from common import ROOT, load_env, report

CONTAINERS = ["auto-ontology-frontend", "auto-ontology", "auto-ontology-ingestion-service", "postgres"]
PORTS = {3000: "web UI", 3001: "backend API", 3002: "ingestion service", 5432: "postgres"}
KNOWN_DEFAULTS = {"change-me", "autoontologypassword123", "myverylongsecret123", "nvapi-your-api-key-here", "password", "postgres"}


def run(*cmd: str) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60).stdout


def listeners() -> dict[int, set[str]]:
    """port -> set of local addresses it listens on, from netstat."""
    out: dict[int, set[str]] = {}
    for line in run("netstat", "-ano", "-p", "tcp").splitlines():
        m = re.match(r"\s*TCP\s+(\S+):(\d+)\s+\S+\s+LISTENING", line)
        if m:
            out.setdefault(int(m.group(2)), set()).add(m.group(1))
    return out


def main() -> int:
    env = load_env()
    listen = listeners()
    loopback = {"127.0.0.1"}

    # 1a. netstat view
    for port, what in PORTS.items():
        addrs = listen.get(port)
        if not addrs:
            report(f"security: port {port} ({what}) bind", "SKIPPED", "not listening (is the stack running?)")
        elif addrs <= loopback:
            report(f"security: port {port} ({what}) bind", "PASS", "listens on 127.0.0.1 only")
        else:
            report(f"security: port {port} ({what}) bind", "FAIL", f"listens on {sorted(addrs)}")
    if 3003 in listen:
        report("security: port 3003 (MCP) bind", "PASS" if listen[3003] <= loopback else "FAIL", f"listens on {sorted(listen[3003])}")
    else:
        report("security: port 3003 (MCP) bind", "SKIPPED", "MCP server not running")

    # 1b. Docker's own view of the published ports
    try:
        info = json.loads(run("docker", "inspect", *CONTAINERS))
        bad = []
        for c in info:
            for cport, binds in (c["HostConfig"].get("PortBindings") or {}).items():
                for b in binds or []:
                    if b.get("HostIp") not in ("127.0.0.1",):
                        bad.append(f"{c['Name'].lstrip('/')} {cport} -> {b.get('HostIp') or '0.0.0.0'}")
        report("security: docker port bindings", "PASS" if not bad else "FAIL",
               "every published port is bound to 127.0.0.1" if not bad else f"not localhost-only: {bad}")
    except Exception as e:
        info = []
        report("security: docker port bindings", "SKIPPED", f"docker inspect failed ({type(e).__name__})")

    # 2. refused on other local IPs
    ips = sorted({ip for ip in socket.gethostbyname_ex(socket.gethostname())[2] if not ip.startswith(("127.", "169.254."))})
    if not ips:
        report("security: not reachable via LAN IP", "SKIPPED", "no non-loopback IPv4 address found")
    else:
        reachable = []
        for ip in ips:
            for port in PORTS:
                s = socket.socket(); s.settimeout(2)
                if s.connect_ex((ip, port)) == 0:
                    reachable.append(f"{ip}:{port}")
                s.close()
        report("security: not reachable via LAN IP", "PASS" if not reachable else "FAIL",
               f"ports {sorted(PORTS)} refused on {len(ips)} other address(es)" if not reachable else f"REACHABLE: {reachable}")

    # 3. default passwords (names only, never values)
    example = {}
    for line in (ROOT / "auto-ontology" / ".env.example").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            example[k.strip()] = v.strip()
    secret_keys = [k for k in example if re.search(r"PASSWORD|SECRET|API_KEY", k)]
    still_default = [k for k in secret_keys if k in env and env[k] == example[k]]
    missing = [k for k in ("POSTGRES_PASSWORD", "AUTO_ONTOLOGY_ADMIN_PASSWORD", "PGADMIN_PASSWORD", "AUTH_SECRET") if k not in env]
    weak = [k for k in ("POSTGRES_PASSWORD", "AUTO_ONTOLOGY_ADMIN_PASSWORD", "PGADMIN_PASSWORD") if k in env and len(env[k]) < 12]
    weak += [k for k in ("AUTH_SECRET",) if k in env and len(env[k]) < 32]
    problems = [f"still the example value: {still_default}"] * bool(still_default) + [f"not set: {missing}"] * bool(missing) + [f"too short: {weak}"] * bool(weak)
    report("security: .env has no default passwords", "PASS" if not problems else "FAIL",
           "POSTGRES/ADMIN/PGADMIN passwords >=12 chars, AUTH_SECRET >=32, none equal to .env.example" if not problems else "; ".join(problems))

    if info:
        hits = []
        for c in info:
            for kv in c["Config"].get("Env") or []:
                k, _, v = kv.partition("=")
                if v in KNOWN_DEFAULTS and re.search(r"PASSWORD|SECRET|KEY", k):
                    hits.append(f"{c['Name'].lstrip('/')}:{k}")
        report("security: containers have no default passwords", "PASS" if not hits else "FAIL",
               "no running container has a known default secret in its environment" if not hits else f"default values in: {hits}")
    else:
        report("security: containers have no default passwords", "SKIPPED", "docker inspect unavailable")

    # 4. KumoRFM
    kumo_env = [k for k in env if k.startswith("KUMO_RFM")]
    kumo_ctr = [f"{c['Name'].lstrip('/')}:{kv.split('=')[0]}" for c in info for kv in (c["Config"].get("Env") or []) if kv.startswith("KUMO_RFM")]
    report("security: KumoRFM disabled", "PASS" if not (kumo_env or kumo_ctr) else "FAIL",
           "no KUMO_RFM_* variable in .env or in any container" if not (kumo_env or kumo_ctr) else f"set: {kumo_env + kumo_ctr}")

    # 5. extras
    running = run("docker", "ps", "--format", "{{.Names}}").split()
    report("security: pgAdmin not running", "PASS" if "pgadmin" not in running else "FAIL", "pgAdmin container is off" if "pgadmin" not in running else "pgadmin is running")
    ign = subprocess.run(["git", "-C", str(ROOT / "auto-ontology"), "check-ignore", "-q", ".env"]).returncode == 0
    report("security: .env git-ignored", "PASS" if ign else "FAIL", "the repo's .gitignore ignores .env" if ign else ".env is NOT ignored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
