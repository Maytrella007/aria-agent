"""
ARIA - System Info Tool
========================

Monitor system resources: CPU, memory, disk, processes, network.
ARIA understands the machine where it lives.
Inspired by OpenClaw's nodes_tool (device_status).
"""

import logging
import os
import platform
import subprocess
from datetime import datetime
from typing import Any, Dict, Optional

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.system_info")

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


class SystemInfoTool(ToolBase):
    """Get system information and monitor resources."""

    name = "system_info"
    description = (
        "Get system information: CPU usage, memory, disk space, running processes, network, uptime. "
        "Actions: overview, cpu, memory, disk, processes, network. "
        "Use to monitor the machine, diagnose issues, or check resource usage."
    )
    parameters = [
        ToolParam(
            name="action",
            type="string",
            description="What info to get: overview, cpu, memory, disk, processes, network",
            required=True,
            enum=["overview", "cpu", "memory", "disk", "processes", "network"],
        ),
        ToolParam(
            name="top_n",
            type="integer",
            description="Number of top processes to show (for 'processes' action, default: 10)",
            required=False,
            default=10,
        ),
    ]

    def _execute(self, **kwargs) -> ToolResult:
        action = kwargs["action"]

        actions = {
            "overview": self._overview,
            "cpu": self._cpu,
            "memory": self._memory,
            "disk": self._disk,
            "processes": self._processes,
            "network": self._network,
        }

        handler = actions.get(action)
        if not handler:
            return ToolResult(success=False, error=f"Unknown action: {action}")

        return handler(kwargs)

    def _overview(self, kwargs) -> ToolResult:
        info = {
            "hostname": platform.node(),
            "os": f"{platform.system()} {platform.release()}",
            "arch": platform.machine(),
            "python": platform.python_version(),
            "time": datetime.now().isoformat()[:19],
        }

        if PSUTIL_AVAILABLE:
            info["cpu_percent"] = f"{psutil.cpu_percent(interval=0.5)}%"
            info["cpu_cores"] = psutil.cpu_count()
            mem = psutil.virtual_memory()
            info["memory_total"] = _fmt_bytes(mem.total)
            info["memory_used"] = f"{_fmt_bytes(mem.used)} ({mem.percent}%)"
            info["memory_available"] = _fmt_bytes(mem.available)
            disk = psutil.disk_usage("/")
            info["disk_total"] = _fmt_bytes(disk.total)
            info["disk_used"] = f"{_fmt_bytes(disk.used)} ({disk.percent}%)"
            info["disk_free"] = _fmt_bytes(disk.free)
            boot = datetime.fromtimestamp(psutil.boot_time())
            info["uptime"] = str(datetime.now() - boot).split(".")[0]
        else:
            info["note"] = "Install psutil for detailed stats: pip install psutil"

        lines = ["System Overview:\n"]
        for k, v in info.items():
            lines.append(f"  {k}: {v}")

        return ToolResult(success=True, output="\n".join(lines), data=info)

    def _cpu(self, kwargs) -> ToolResult:
        if not PSUTIL_AVAILABLE:
            return self._fallback_cmd("cpu", "lscpu 2>/dev/null || sysctl -a 2>/dev/null | grep cpu")

        info = {
            "percent": psutil.cpu_percent(interval=1, percpu=True),
            "total_percent": psutil.cpu_percent(interval=0),
            "cores_physical": psutil.cpu_count(logical=False),
            "cores_logical": psutil.cpu_count(logical=True),
            "freq": None,
        }

        try:
            freq = psutil.cpu_freq()
            if freq:
                info["freq"] = f"{freq.current:.0f} MHz"
        except Exception:
            pass

        lines = [f"CPU Usage: {info['total_percent']}%"]
        lines.append(f"Cores: {info['cores_physical']} physical, {info['cores_logical']} logical")
        if info["freq"]:
            lines.append(f"Frequency: {info['freq']}")
        lines.append(f"Per-core: {', '.join(f'{p}%' for p in info['percent'])}")

        return ToolResult(success=True, output="\n".join(lines), data=info)

    def _memory(self, kwargs) -> ToolResult:
        if not PSUTIL_AVAILABLE:
            return self._fallback_cmd("memory", "free -h 2>/dev/null || vm_stat 2>/dev/null")

        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()

        info = {
            "total": _fmt_bytes(mem.total),
            "used": _fmt_bytes(mem.used),
            "available": _fmt_bytes(mem.available),
            "percent": f"{mem.percent}%",
            "swap_total": _fmt_bytes(swap.total),
            "swap_used": _fmt_bytes(swap.used),
            "swap_percent": f"{swap.percent}%",
        }

        lines = ["Memory:"]
        lines.append(f"  RAM: {info['used']} / {info['total']} ({info['percent']})")
        lines.append(f"  Available: {info['available']}")
        lines.append(f"  Swap: {info['swap_used']} / {info['swap_total']} ({info['swap_percent']})")

        return ToolResult(success=True, output="\n".join(lines), data=info)

    def _disk(self, kwargs) -> ToolResult:
        if not PSUTIL_AVAILABLE:
            return self._fallback_cmd("disk", "df -h")

        partitions = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                partitions.append({
                    "mount": part.mountpoint,
                    "device": part.device,
                    "fstype": part.fstype,
                    "total": _fmt_bytes(usage.total),
                    "used": _fmt_bytes(usage.used),
                    "free": _fmt_bytes(usage.free),
                    "percent": f"{usage.percent}%",
                })
            except PermissionError:
                continue

        lines = ["Disk Usage:\n"]
        for p in partitions:
            lines.append(f"  {p['mount']} ({p['device']}, {p['fstype']})")
            lines.append(f"    {p['used']} / {p['total']} ({p['percent']}) — {p['free']} free")

        return ToolResult(success=True, output="\n".join(lines), data={"partitions": partitions})

    def _processes(self, kwargs) -> ToolResult:
        top_n = min(kwargs.get("top_n", 10), 30)

        if not PSUTIL_AVAILABLE:
            return self._fallback_cmd("processes", f"ps aux --sort=-%mem | head -{top_n + 1}")

        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status"]):
            try:
                info = p.info
                procs.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # Sort by memory usage
        procs.sort(key=lambda x: x.get("memory_percent", 0) or 0, reverse=True)
        top = procs[:top_n]

        lines = [f"Top {len(top)} processes (by memory):\n"]
        lines.append(f"  {'PID':>7}  {'CPU%':>5}  {'MEM%':>5}  {'STATUS':<10}  NAME")
        for p in top:
            lines.append(
                f"  {p['pid']:>7}  {p.get('cpu_percent', 0) or 0:>5.1f}  "
                f"{p.get('memory_percent', 0) or 0:>5.1f}  {p.get('status', '?'):<10}  "
                f"{p.get('name', '?')}"
            )

        return ToolResult(
            success=True, output="\n".join(lines),
            data={"total_processes": len(procs), "top": top},
        )

    def _network(self, kwargs) -> ToolResult:
        if not PSUTIL_AVAILABLE:
            return self._fallback_cmd("network", "ip addr 2>/dev/null || ifconfig 2>/dev/null")

        counters = psutil.net_io_counters()
        info = {
            "bytes_sent": _fmt_bytes(counters.bytes_sent),
            "bytes_recv": _fmt_bytes(counters.bytes_recv),
            "packets_sent": counters.packets_sent,
            "packets_recv": counters.packets_recv,
            "errors_in": counters.errin,
            "errors_out": counters.errout,
        }

        # Get interfaces
        interfaces = []
        addrs = psutil.net_if_addrs()
        for name, addr_list in addrs.items():
            for addr in addr_list:
                if addr.family.name == "AF_INET":
                    interfaces.append({"name": name, "ip": addr.address})

        lines = ["Network:"]
        lines.append(f"  Sent: {info['bytes_sent']} | Received: {info['bytes_recv']}")
        lines.append(f"  Packets: {info['packets_sent']} out / {info['packets_recv']} in")
        if info["errors_in"] or info["errors_out"]:
            lines.append(f"  Errors: {info['errors_in']} in / {info['errors_out']} out")
        lines.append("\n  Interfaces:")
        for iface in interfaces:
            lines.append(f"    {iface['name']}: {iface['ip']}")

        return ToolResult(
            success=True, output="\n".join(lines),
            data={**info, "interfaces": interfaces},
        )

    def _fallback_cmd(self, name: str, cmd: str) -> ToolResult:
        """Fallback when psutil not available."""
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            output = result.stdout.strip() or result.stderr.strip() or "(no output)"
            return ToolResult(
                success=True,
                output=f"{name} (psutil not available, using fallback):\n{output}",
                data={"fallback": True},
            )
        except Exception as e:
            return ToolResult(success=False, error=f"psutil not installed and fallback failed: {e}")


def _fmt_bytes(n: int) -> str:
    """Format bytes to human-readable."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"
