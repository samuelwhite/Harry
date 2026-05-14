from __future__ import annotations

from contextlib import contextmanager

from app.ui import inventory as inventory_ui
from app.ui import fleet as fleet_ui


def test_inventory_helpers_show_all_disks_gpus_and_network_interfaces():
    disks = [
        {"name": "Disk 1", "type": "NVMe", "size_gb": 512},
        {"name": "Disk 2", "type": "SATA", "size_gb": 1024},
        {"name": "Disk 3", "type": "SATA", "size_gb": 2048},
        {"name": "Disk 4", "type": "USB", "size_gb": 256},
    ]
    gpus = [
        {"name": "NVIDIA RTX 3080", "mem_total_mb": 10240, "capability_hint": "CUDA capable"},
        {"name": "Intel Iris Xe", "mem_total_mb": 512, "capability_hint": "Integrated graphics"},
        {"name": "AMD Radeon RX 7800 XT", "mem_total_mb": 16384, "capability_hint": "Dedicated graphics"},
    ]
    nics = [
        {"name": "Ethernet", "ip": "192.168.1.10", "mac": "aa:bb:cc:dd:ee:ff", "speed_mbps": 1000},
        {"name": "Wi-Fi", "ip": "192.168.1.11", "mac": "11:22:33:44:55:66", "speed_mbps": 866},
    ]

    disk_text = inventory_ui._fmt_disk_brief(disks)
    gpu_text = inventory_ui._fmt_gpu_brief(gpus, {})
    nic_text = inventory_ui._fmt_nic_brief(nics)

    assert "Disk 1" in disk_text
    assert "Disk 4" in disk_text
    assert "NVIDIA RTX 3080" in gpu_text
    assert "AMD Radeon RX 7800 XT" in gpu_text
    assert "Ethernet" in nic_text
    assert "Wi-Fi" in nic_text
    assert "+1 more" not in disk_text
    assert "+1 more" not in gpu_text
    assert "+X more" not in disk_text
    assert "+X more" not in gpu_text


def test_inventory_row_preserves_complete_hardware_lists():
    payload = {
        "facts": {
            "disks": [
                {"name": "Disk 1", "type": "NVMe", "size_gb": 512},
                {"name": "Disk 2", "type": "SATA", "size_gb": 1024},
            ],
            "gpus": [
                {"name": "NVIDIA RTX 3080", "mem_total_mb": 10240, "capability_hint": "CUDA capable"},
                {"name": "Intel Iris Xe", "mem_total_mb": 512, "capability_hint": "Integrated graphics"},
            ],
            "network_interfaces": [
                {"name": "Ethernet", "ip": "192.168.1.10", "mac": "aa:bb:cc:dd:ee:ff", "speed_mbps": 1000}
            ],
        },
        "metrics": {"disk_used": [], "temps_c": {}, "gpu": [], "extensions": {}},
        "derived": {"health": {"state": "healthy", "worst_severity": "ok", "reasons": []}, "extensions": {}},
        "advice": [],
    }

    row = inventory_ui._inventory_row("node-1", payload, "2026-05-07T12:00:00Z")

    assert len(row["disks"]) == 2
    assert len(row["gpus"]) == 2
    assert len(row["network_interfaces"]) == 1


def test_inventory_page_hides_empty_network_interfaces(monkeypatch):
    @contextmanager
    def fake_db():
        yield object()

    latest = {
        "node-1": {
            "ts": "2026-05-10T12:00:00Z",
            "payload": {
                "facts": {
                    "disks": [{"name": "Disk 1", "type": "NVMe", "size_gb": 512}],
                    "gpus": [{"name": "NVIDIA RTX 3080", "mem_total_mb": 10240}],
                },
                "metrics": {"disk_used": [], "temps_c": {}, "gpu": [], "extensions": {}},
                "derived": {"health": {"state": "healthy", "worst_severity": "ok", "reasons": []}, "extensions": {}},
                "advice": [],
            },
        }
    }

    monkeypatch.setattr(inventory_ui, "_db", fake_db)
    monkeypatch.setattr(inventory_ui, "_db_has_ingest", lambda conn: True)
    monkeypatch.setattr(inventory_ui, "_fetch_latest_per_node", lambda conn: latest)

    html = inventory_ui.render_inventory_page(hours=24, debug=False)

    assert "Network interfaces" not in html
    assert "Disk 1" in html
    assert "NVIDIA RTX 3080" in html


def test_inventory_page_renders_network_interfaces_when_present(monkeypatch):
    @contextmanager
    def fake_db():
        yield object()

    latest = {
        "node-1": {
            "ts": "2026-05-10T12:00:00Z",
            "payload": {
                "facts": {
                    "network_interfaces": [
                        {"name": "Ethernet", "ip": "192.168.1.10", "mac": "aa:bb:cc:dd:ee:ff", "speed_mbps": 1000}
                    ]
                },
                "metrics": {"disk_used": [], "temps_c": {}, "gpu": [], "extensions": {}},
                "derived": {"health": {"state": "healthy", "worst_severity": "ok", "reasons": []}, "advice": []},
                "advice": [],
            },
        }
    }

    monkeypatch.setattr(inventory_ui, "_db", fake_db)
    monkeypatch.setattr(inventory_ui, "_db_has_ingest", lambda conn: True)
    monkeypatch.setattr(inventory_ui, "_fetch_latest_per_node", lambda conn: latest)

    html = inventory_ui.render_inventory_page(hours=24, debug=False)

    assert "Network interfaces" in html
    assert "Ethernet" in html


def test_fleet_storage_panel_renders_synology_volume_mounts():
    html = fleet_ui._render_storage_physical(
        [],
        [
            {
                "mount": "/volume1",
                "fs": "/dev/vg1/volume_1",
                "device": "/dev/vg1/volume_1",
                "total_b": 1000000,
                "used_b": 400000,
                "free_b": 600000,
                "used_pct": 40.0,
            },
            {
                "mount": "/volume2",
                "fs": "/dev/vg2/volume_2",
                "device": "/dev/vg2/volume_2",
                "total_b": 2000000,
                "used_b": 500000,
                "free_b": 1500000,
                "used_pct": 25.0,
            },
        ],
    )

    assert "DSM volumes" in html
    assert "/volume1" in html
    assert "/dev/vg1/volume_1" in html
    assert "Total" in html
    assert "Used" in html
    assert "Free" in html
