"""TR-064-Zugriff auf die FRITZ!Box: Mesh-Topologie und Host-Liste (nur lesend)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from .config import app_options, in_ha_app

ENV_FILE = Path(os.environ.get("FRITZ_ENV", Path.home() / ".config" / "fritz.env"))
TR064_PORT = 49000


def _read_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        env[key.strip()] = value
    return env


@dataclass
class FritzBox:
    host: str
    user: str
    password: str
    timeout: float = 15.0

    @classmethod
    def from_env(cls, path: Path | None = None) -> FritzBox:
        env = _read_env(path or ENV_FILE)    # erst beim Aufruf auflösen (Tests lenken ENV_FILE um)
        return cls(env.get("FRITZ_HOST", "fritz.box"), env["FRITZ_USERNAME"], env["FRITZ_PASSWORD"])

    @classmethod
    def configured(cls) -> FritzBox:
        """Zugang aus der App-Konfiguration in Home Assistant, sonst aus ENV_FILE."""
        opts = app_options()
        if opts.get("fritzbox_password"):
            return cls(opts.get("fritzbox_host") or "fritz.box", opts.get("fritzbox_user") or "", opts["fritzbox_password"])
        if not in_ha_app() and ENV_FILE.exists():
            return cls.from_env()
        where = "in der Konfiguration der App" if in_ha_app() else f"in {ENV_FILE}"
        raise RuntimeError(f"Kein Zugang zur FRITZ!Box eingerichtet ({where} eintragen)")

    @property
    def base(self) -> str:
        return f"http://{self.host}:{TR064_PORT}"

    def _opener(self) -> urllib.request.OpenerDirector:
        mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        mgr.add_password(None, self.base, self.user, self.password)
        return urllib.request.build_opener(urllib.request.HTTPDigestAuthHandler(mgr))

    def soap(self, control_url: str, service: str, action: str, args: dict[str, str] | None = None) -> dict[str, str]:
        inner = "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in (args or {}).items())
        body = (
            '<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            f'<u:{action} xmlns:u="{service}">{inner}</u:{action}></s:Body></s:Envelope>'
        )
        req = urllib.request.Request(
            self.base + control_url,
            body.encode(),
            {"Content-Type": 'text/xml; charset="utf-8"', "SoapAction": f"{service}#{action}"},
        )
        with self._opener().open(req, timeout=self.timeout) as resp:
            root = ET.fromstring(resp.read())
        result = root.find(f".//{{{service}}}{action}Response")
        return {child.tag: (child.text or "") for child in (result if result is not None else [])}

    def _fetch(self, path: str) -> bytes:
        url = path if path.startswith("http") else self.base + path
        with self._opener().open(url, timeout=self.timeout) as resp:
            return resp.read()

    def mesh_list(self) -> dict:
        res = self.soap("/upnp/control/hosts", "urn:dslforum-org:service:Hosts:1", "X_AVM-DE_GetMeshListPath")
        return json.loads(self._fetch(res["NewX_AVM-DE_MeshListPath"]))

    def host_by_ip(self, ip: str) -> dict[str, str] | None:
        """MAC-Adresse und Name des Geräts mit dieser IP-Adresse (Host-Liste); None, wenn unbekannt."""
        try:
            res = self.soap("/upnp/control/hosts", "urn:dslforum-org:service:Hosts:1",
                            "X_AVM-DE_GetSpecificHostEntryByIP", {"NewIPAddress": ip})
        except urllib.error.HTTPError:      # SOAP-Fehler (HTTP 500): IP unbekannt
            return None
        mac = res.get("NewMACAddress")
        return {"mac": mac, "name": res.get("NewHostName", "")} if mac else None

    def host_list(self) -> list[dict[str, str]]:
        res = self.soap("/upnp/control/hosts", "urn:dslforum-org:service:Hosts:1", "X_AVM-DE_GetHostListPath")
        root = ET.fromstring(self._fetch(res["NewX_AVM-DE_HostListPath"]))
        return [{child.tag: (child.text or "") for child in item} for item in root.iter("Item")]
