import logging
import re
from datetime import datetime

from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException

logger = logging.getLogger("juniper_monitor.collector")

COMMANDS = {
    "version": "show version",
    "uptime": "show system uptime",
    "hardware": "show chassis hardware",
    "environment": "show chassis environment",
    "routing_engine": "show chassis routing-engine",
    "storage": "show system storage",
    "system_alarms": "show system alarms",
    "chassis_alarms": "show chassis alarms",
    "interfaces_terse": "show interfaces terse",
    "interfaces_extensive": "show interfaces extensive | match \"Physical interface|Input errors|Output errors|CRC\"",
    "power": "show chassis power",
    "log_messages": "show log messages | last 100",
    "arp": "show arp",
    "ethernet_switching": "show ethernet-switching table summary",
    "lldp_neighbors": "show lldp neighbors",
}


class CollectionError(Exception):
    pass


def _connect(switch: dict):
    return ConnectHandler(
        device_type="juniper_junos",
        host=switch["host"],
        port=switch.get("port", 22),
        username=switch["username"],
        password=switch["password"],
        timeout=20,
        session_timeout=60,
        fast_cli=False,
    )


def collect_raw(switch: dict) -> dict:
    """SSH into the switch and run all show commands. Returns {key: raw_text}."""
    raw = {}
    try:
        conn = _connect(switch)
    except NetmikoAuthenticationException as e:
        raise CollectionError(f"Authentication failed: {e}")
    except NetmikoTimeoutException as e:
        raise CollectionError(f"Connection timed out: {e}")
    except Exception as e:
        raise CollectionError(f"Connection failed: {e}")

    try:
        for key, cmd in COMMANDS.items():
            try:
                raw[key] = conn.send_command(cmd, read_timeout=30)
            except Exception as e:
                raw[key] = f"<error running '{cmd}': {e}>"
                logger.warning("Command %s failed on %s: %s", cmd, switch["host"], e)
    finally:
        conn.disconnect()

    return raw


# ---- parsing helpers -------------------------------------------------

def _search(pattern, text, group=1, flags=re.IGNORECASE):
    m = re.search(pattern, text or "", flags)
    return m.group(group) if m else None


def _count(pattern, text, flags=re.IGNORECASE | re.MULTILINE):
    return len(re.findall(pattern, text or "", flags))


def parse_version(text):
    model = _search(r"Model:\s*(\S+)", text)
    junos = _search(r"Junos:\s*(\S+)", text)
    hostname = _search(r"Hostname:\s*(\S+)", text)
    return {"model": model, "junos_version": junos, "hostname": hostname}


def parse_uptime(text):
    uptime_str = _search(r"^\s*\d+:\d+(?:AM|PM)?\s+up\s+(.+?),\s*\d+\s*user", text, flags=re.IGNORECASE | re.MULTILINE)
    if not uptime_str:
        uptime_str = _search(r"up\s+(\d+\s*days?,\s*[\d:]+)", text)
    booted = _search(r"System booted:\s*(.+?)\s*\(", text)
    load_avgs = _search(r"load averages?:\s*([\d.,\s]+)", text)
    uptime_days = None
    m = re.search(r"(\d+)\s*days?,\s*(\d+):(\d+)", text or "", re.IGNORECASE)
    if m:
        days, hh, mm = int(m.group(1)), int(m.group(2)), int(m.group(3))
        uptime_days = round(days + hh / 24 + mm / 1440, 3)
    load1 = None
    if load_avgs:
        parts = [p.strip() for p in load_avgs.split(",")]
        if parts:
            try:
                load1 = float(parts[0])
            except ValueError:
                load1 = None
    return {
        "uptime_text": uptime_str,
        "booted_text": booted,
        "load_average_1m": load1,
        "uptime_days": uptime_days,
    }


def parse_routing_engine(text):
    cpu_idle = _search(r"Idle\s+(\d+)\s*percent", text)
    mem_util = _search(r"Memory utilization\s+(\d+)\s*percent", text)
    temp = _search(r"^\s*Temperature\s+(\d+)\s*degrees C", text, flags=re.IGNORECASE | re.MULTILINE)
    cpu_util = None
    if cpu_idle is not None:
        try:
            cpu_util = 100 - int(cpu_idle)
        except ValueError:
            cpu_util = None
    return {
        "cpu_util_pct": cpu_util,
        "memory_util_pct": float(mem_util) if mem_util else None,
        "re_temperature_c": float(temp) if temp else None,
    }


def parse_storage(text):
    # root filesystem usage line, e.g: /dev/... 1.9G 900M 900M 50% /
    pct = None
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) >= 6 and parts[-1] == "/":
            use_pct = parts[-2].rstrip("%")
            try:
                pct = float(use_pct)
            except ValueError:
                pct = None
            break
    return {"root_storage_used_pct": pct}


def parse_alarms(text):
    if text and "no" in text.lower() and "alarm" in text.lower():
        return 0
    return _count(r"^\S.+", text)


def parse_interfaces_terse(text):
    up = down = 0
    for line in (text or "").splitlines()[1:]:
        parts = line.split()
        if len(parts) < 3:
            continue
        admin, link = parts[1], parts[2]
        if admin == "up" and link == "up":
            up += 1
        elif admin == "up" and link == "down":
            down += 1
    return {"interfaces_up": up, "interfaces_down": down}


def parse_power(text):
    online = _count(r"\bOnline\b", text)
    total = _count(r"^(PEM|Power Supply)\s*\d+", text)
    return {"power_supplies_online": online, "power_supplies_total": total or online}


def parse_arp(text):
    lines = [l for l in (text or "").splitlines() if re.match(r"^[0-9a-fA-F]{1,3}\.", l) or re.match(r"^\S+\s+[0-9a-f]{2}:[0-9a-f]{2}", l, re.IGNORECASE)]
    return {"arp_entries": len(lines)}


def parse_ethernet_switching(text):
    count = _search(r"(\d+)\s+MAC address(?:es)?", text)
    return {"mac_count": int(count) if count else None}


def parse_all(raw: dict):
    """Returns (summary, metrics) where summary is rich per-section data for the UI
    and metrics is a flat {name: float} dict suitable for time-series storage."""
    version = parse_version(raw.get("version", ""))
    uptime = parse_uptime(raw.get("uptime", ""))
    re_stats = parse_routing_engine(raw.get("routing_engine", ""))
    storage = parse_storage(raw.get("storage", ""))
    ifaces = parse_interfaces_terse(raw.get("interfaces_terse", ""))
    power = parse_power(raw.get("power", ""))
    arp = parse_arp(raw.get("arp", ""))
    eth = parse_ethernet_switching(raw.get("ethernet_switching", ""))
    sys_alarm_count = parse_alarms(raw.get("system_alarms", ""))
    chassis_alarm_count = parse_alarms(raw.get("chassis_alarms", ""))

    summary = {
        "collected_at": datetime.utcnow().isoformat() + "Z",
        "version": version,
        "uptime": uptime,
        "routing_engine": re_stats,
        "storage": storage,
        "interfaces": ifaces,
        "power": power,
        "arp": arp,
        "ethernet_switching": eth,
        "alarms": {"system": sys_alarm_count, "chassis": chassis_alarm_count},
    }

    metrics = {
        "cpu_util_pct": re_stats.get("cpu_util_pct"),
        "memory_util_pct": re_stats.get("memory_util_pct"),
        "re_temperature_c": re_stats.get("re_temperature_c"),
        "uptime_days": uptime.get("uptime_days"),
        "load_average_1m": uptime.get("load_average_1m"),
        "root_storage_used_pct": storage.get("root_storage_used_pct"),
        "interfaces_up": ifaces.get("interfaces_up"),
        "interfaces_down": ifaces.get("interfaces_down"),
        "arp_entries": arp.get("arp_entries"),
        "mac_count": eth.get("mac_count"),
        "system_alarm_count": sys_alarm_count,
        "chassis_alarm_count": chassis_alarm_count,
        "power_supplies_online": power.get("power_supplies_online"),
    }

    return summary, metrics


def collect_and_parse(switch: dict):
    raw = collect_raw(switch)
    summary, metrics = parse_all(raw)
    return summary, metrics, raw
