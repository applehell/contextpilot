"""Kubernetes connector — sync deployments, services, configmaps, pods, and ingresses."""
from __future__ import annotations

import hashlib
import json
import ssl
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from ..storage.memory import Memory, MemoryStore
from .base import ConfigField, ConnectorPlugin, SyncResult

SYNC_ITEM_KINDS = {
    "deployments": ("apps/v1", "deployments"),
    "services": ("v1", "services"),
    "configmaps": ("v1", "configmaps"),
    "pods": ("v1", "pods"),
    "ingresses": ("networking.k8s.io/v1", "ingresses"),
}

BLOCKED_KINDS = {"secrets", "secret", "serviceaccounttokens"}


class _K8sAPI:
    def __init__(self, api_url: str, token: str = "", kubeconfig_path: str = "", verify_tls: bool = True) -> None:
        self.base_url = api_url.rstrip("/")
        self.token = token
        self.verify_tls = verify_tls
        self._ssl_ctx: Optional[ssl.SSLContext] = None

        if not self.token and kubeconfig_path:
            self.token = self._token_from_kubeconfig(kubeconfig_path)

        if not self.verify_tls:
            self._ssl_ctx = ssl.create_default_context()
            self._ssl_ctx.check_hostname = False
            self._ssl_ctx.verify_mode = ssl.CERT_NONE

    @staticmethod
    def _token_from_kubeconfig(path: str) -> str:
        try:
            with open(path) as f:
                kc = json.loads(f.read()) if path.endswith(".json") else None
                if kc is None:
                    f.seek(0)
                    import yaml  # noqa: delayed import — only needed for kubeconfig
                    kc = yaml.safe_load(f)
        except Exception:
            return ""

        if not kc or not isinstance(kc, dict):
            return ""

        users = kc.get("users", [])
        if users and isinstance(users, list):
            user_data = users[0].get("user", {})
            token = user_data.get("token", "")
            if token:
                return token
            auth_provider = user_data.get("auth-provider", {})
            if auth_provider:
                return auth_provider.get("config", {}).get("access-token", "")
        return ""

    def _get(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15, context=self._ssl_ctx) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise ValueError("401 Unauthorized — check your bearer token or kubeconfig.")
            if e.code == 403:
                raise ValueError("403 Forbidden — the ServiceAccount lacks permissions for this resource.")
            raise

    def namespaces(self) -> List[str]:
        data = self._get("/api/v1/namespaces")
        return [ns["metadata"]["name"] for ns in data.get("items", [])]

    def list_resource(self, api_group: str, kind: str, namespace: str) -> List[Dict]:
        if api_group == "v1":
            path = f"/api/v1/namespaces/{namespace}/{kind}"
        else:
            path = f"/apis/{api_group}/namespaces/{namespace}/{kind}"
        try:
            data = self._get(path)
            return data.get("items", [])
        except Exception:
            return []


class KubernetesConnector(ConnectorPlugin):
    name = "kubernetes"
    display_name = "Kubernetes"
    description = "Sync deployments, services, configmaps, pods, and ingresses from a Kubernetes cluster"
    icon = "K8"
    category = "Infrastructure"
    setup_guide = "Provide your cluster API URL and a bearer token (from a ServiceAccount). Or use a kubeconfig file path."
    color = "#326ce5"

    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField("api_url", "API URL", placeholder="https://k8s.example.com:6443", required=True),
            ConfigField("token", "Bearer Token", type="password",
                        placeholder="ServiceAccount token (or leave empty if using kubeconfig)"),
            ConfigField("kubeconfig_path", "Kubeconfig Path", type="text",
                        placeholder="/home/user/.kube/config (optional)"),
            ConfigField("namespaces", "Namespaces", type="text",
                        placeholder="default,kube-system (empty = all)"),
            ConfigField("sync_items", "Sync Items", type="text",
                        placeholder="deployments,services,configmaps,pods,ingresses",
                        default="deployments,services,configmaps,pods"),
            ConfigField("verify_tls", "Verify TLS", type="boolean", default=True),
        ]

    @property
    def configured(self) -> bool:
        return bool(self._config.get("api_url") and (self._config.get("token") or self._config.get("kubeconfig_path")))

    def _api(self) -> _K8sAPI:
        verify = self._config.get("verify_tls", True)
        if isinstance(verify, str):
            verify = verify.lower() not in ("false", "0", "no", "")
        return _K8sAPI(
            api_url=self._config["api_url"],
            token=self._config.get("token", ""),
            kubeconfig_path=self._config.get("kubeconfig_path", ""),
            verify_tls=verify,
        )

    def _parse_list(self, raw: str) -> List[str]:
        if not raw:
            return []
        return [x.strip().lower() for x in raw.split(",") if x.strip()]

    def test_connection(self) -> Dict[str, Any]:
        if not self.configured:
            return {"ok": False, "error": "Not configured"}
        try:
            api = self._api()
            ns_list = api.namespaces()
            return {
                "ok": True,
                "namespace_count": len(ns_list),
                "namespaces": ns_list[:10],
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def sync(self, store: MemoryStore) -> SyncResult:
        if not self.configured:
            r = SyncResult()
            r.errors.append("Not configured")
            return r

        result = SyncResult()
        api = self._api()
        prefix = f"k8s/"

        configured_ns = self._parse_list(self._config.get("namespaces", ""))
        sync_items_raw = self._config.get("sync_items", "deployments,services,configmaps,pods")
        sync_items = self._parse_list(sync_items_raw) or ["deployments", "services", "configmaps", "pods"]
        sync_items = [s for s in sync_items if s not in BLOCKED_KINDS and s in SYNC_ITEM_KINDS]

        try:
            if configured_ns:
                namespaces = configured_ns
            else:
                namespaces = api.namespaces()
        except Exception as e:
            result.errors.append(f"Failed to list namespaces: {e}")
            return result

        synced_keys = set()
        expires_at = self._compute_expires_at()

        for ns in namespaces:
            for item_name in sync_items:
                api_group, kind = SYNC_ITEM_KINDS[item_name]
                try:
                    resources = api.list_resource(api_group, kind, ns)
                except Exception as e:
                    result.errors.append(f"{ns}/{kind}: {e}")
                    continue

                for resource in resources:
                    meta = resource.get("metadata", {})
                    name = meta.get("name", "")
                    if not name:
                        continue

                    result.total_remote += 1
                    key = f"{prefix}{ns}/{kind}/{name}"
                    synced_keys.add(key)

                    content = self._format_resource(kind, resource)
                    content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
                    mem_tags = ["kubernetes", ns, kind]

                    try:
                        existing = store.get(key)
                        if existing.metadata.get("content_hash") == content_hash:
                            result.skipped += 1
                            continue
                        existing.value = content
                        existing.tags = mem_tags
                        existing.metadata["content_hash"] = content_hash
                        existing.updated_at = time.time()
                        if expires_at:
                            existing.expires_at = expires_at
                        store.set(existing)
                        result.updated += 1
                    except KeyError:
                        mem = Memory(
                            key=key, value=content, tags=mem_tags,
                            metadata={
                                "source": self.name,
                                "content_hash": content_hash,
                                "namespace": ns,
                                "kind": kind,
                                "resource_name": name,
                            },
                            expires_at=expires_at,
                        )
                        store.set(mem)
                        result.added += 1

        for m in store.list():
            if m.key.startswith(prefix) and m.key not in synced_keys:
                store.delete(m.key)
                result.removed += 1

        self._update_sync_stats(len(synced_keys))
        return result

    def _format_resource(self, kind: str, resource: Dict) -> str:
        meta = resource.get("metadata", {})
        name = meta.get("name", "")
        namespace = meta.get("namespace", "")
        labels = meta.get("labels", {})

        parts = [f"# {kind}/{name}", f"Namespace: {namespace}"]

        if labels:
            label_str = ", ".join(f"{k}={v}" for k, v in sorted(labels.items()))
            parts.append(f"Labels: {label_str}")

        if kind == "deployments":
            self._format_deployment(resource, parts)
        elif kind == "pods":
            self._format_pod(resource, parts)
        elif kind == "services":
            self._format_service(resource, parts)
        elif kind == "configmaps":
            self._format_configmap(resource, parts)
        elif kind == "ingresses":
            self._format_ingress(resource, parts)

        return "\n".join(parts)

    @staticmethod
    def _format_deployment(resource: Dict, parts: List[str]) -> None:
        spec = resource.get("spec", {})
        status = resource.get("status", {})
        replicas = spec.get("replicas", 0)
        ready = status.get("readyReplicas", 0)
        available = status.get("availableReplicas", 0)
        parts.append(f"Replicas: {ready}/{replicas} ready, {available} available")

        strategy = spec.get("strategy", {}).get("type", "")
        if strategy:
            parts.append(f"Strategy: {strategy}")

        containers = spec.get("template", {}).get("spec", {}).get("containers", [])
        for c in containers:
            parts.append(f"Container: {c.get('name', '')} image={c.get('image', '')}")
            ports = c.get("ports", [])
            for p in ports:
                parts.append(f"  Port: {p.get('containerPort', '')} ({p.get('protocol', 'TCP')})")
            resources = c.get("resources", {})
            if resources:
                req = resources.get("requests", {})
                lim = resources.get("limits", {})
                if req:
                    parts.append(f"  Requests: cpu={req.get('cpu', '-')} mem={req.get('memory', '-')}")
                if lim:
                    parts.append(f"  Limits: cpu={lim.get('cpu', '-')} mem={lim.get('memory', '-')}")

        conditions = status.get("conditions", [])
        for cond in conditions:
            if cond.get("type") == "Available":
                parts.append(f"Available: {cond.get('status', '')} ({cond.get('reason', '')})")

    @staticmethod
    def _format_pod(resource: Dict, parts: List[str]) -> None:
        status = resource.get("status", {})
        phase = status.get("phase", "")
        parts.append(f"Phase: {phase}")

        pod_ip = status.get("podIP", "")
        if pod_ip:
            parts.append(f"Pod IP: {pod_ip}")

        node = resource.get("spec", {}).get("nodeName", "")
        if node:
            parts.append(f"Node: {node}")

        container_statuses = status.get("containerStatuses", [])
        for cs in container_statuses:
            ready = cs.get("ready", False)
            restarts = cs.get("restartCount", 0)
            image = cs.get("image", "")
            parts.append(f"Container: {cs.get('name', '')} ready={ready} restarts={restarts} image={image}")

            state = cs.get("state", {})
            for state_name, state_detail in state.items():
                if isinstance(state_detail, dict):
                    reason = state_detail.get("reason", "")
                    msg = state_detail.get("message", "")
                    info = f"State: {state_name}"
                    if reason:
                        info += f" reason={reason}"
                    if msg:
                        info += f" msg={msg[:100]}"
                    parts.append(f"  {info}")

    @staticmethod
    def _format_service(resource: Dict, parts: List[str]) -> None:
        spec = resource.get("spec", {})
        svc_type = spec.get("type", "ClusterIP")
        cluster_ip = spec.get("clusterIP", "")
        parts.append(f"Type: {svc_type}")
        if cluster_ip:
            parts.append(f"ClusterIP: {cluster_ip}")

        external_ips = spec.get("externalIPs", [])
        if external_ips:
            parts.append(f"ExternalIPs: {', '.join(external_ips)}")

        lb = resource.get("status", {}).get("loadBalancer", {}).get("ingress", [])
        for entry in lb:
            ip = entry.get("ip", entry.get("hostname", ""))
            if ip:
                parts.append(f"LoadBalancer: {ip}")

        ports = spec.get("ports", [])
        for p in ports:
            port_str = f"{p.get('port', '')}"
            target = p.get("targetPort", "")
            node_port = p.get("nodePort", "")
            proto = p.get("protocol", "TCP")
            name = p.get("name", "")
            line = f"Port: {port_str}->{target} ({proto})"
            if name:
                line = f"Port: {name} {port_str}->{target} ({proto})"
            if node_port:
                line += f" nodePort={node_port}"
            parts.append(line)

        selector = spec.get("selector", {})
        if selector:
            sel_str = ", ".join(f"{k}={v}" for k, v in sorted(selector.items()))
            parts.append(f"Selector: {sel_str}")

    @staticmethod
    def _format_configmap(resource: Dict, parts: List[str]) -> None:
        data = resource.get("data", {})
        if not data:
            parts.append("Data: (empty)")
            return
        parts.append(f"Keys: {', '.join(sorted(data.keys()))}")
        for k, v in sorted(data.items()):
            preview = v[:200] if len(v) > 200 else v
            parts.append(f"  {k}: {preview}")
            if len(v) > 200:
                parts.append(f"  ... ({len(v)} chars total)")

    @staticmethod
    def _format_ingress(resource: Dict, parts: List[str]) -> None:
        spec = resource.get("spec", {})
        tls = spec.get("tls", [])
        if tls:
            hosts = []
            for t in tls:
                hosts.extend(t.get("hosts", []))
            if hosts:
                parts.append(f"TLS Hosts: {', '.join(hosts)}")

        rules = spec.get("rules", [])
        for rule in rules:
            host = rule.get("host", "*")
            http = rule.get("http", {})
            paths = http.get("paths", [])
            for p in paths:
                path = p.get("path", "/")
                path_type = p.get("pathType", "")
                backend = p.get("backend", {})
                svc = backend.get("service", {})
                svc_name = svc.get("name", "")
                svc_port = svc.get("port", {})
                port_num = svc_port.get("number", svc_port.get("name", ""))
                parts.append(f"Rule: {host}{path} ({path_type}) -> {svc_name}:{port_num}")

        ingress_class = spec.get("ingressClassName", "")
        if ingress_class:
            parts.append(f"IngressClass: {ingress_class}")

        lb = resource.get("status", {}).get("loadBalancer", {}).get("ingress", [])
        for entry in lb:
            ip = entry.get("ip", entry.get("hostname", ""))
            if ip:
                parts.append(f"Address: {ip}")
