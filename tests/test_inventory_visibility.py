from __future__ import annotations

from app.ui import inventory as inventory_ui


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
