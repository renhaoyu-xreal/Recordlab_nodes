from recordlab_nodes.common.device_checker import _USB_PRODUCT_CATALOG


def catalog_by_name():
    result = {}
    for entry in _USB_PRODUCT_CATALOG:
        names = list(entry.get("names") or [entry.get("name")])
        for name in names:
            result[name] = entry
    return result


def test_usb_catalog_groups_match_recordlab_device_colors():
    catalog = catalog_by_name()

    for name in ("Air", "P55", "Flora", "Helen", "Helen Pro"):
        entry = catalog[name]
        assert entry["device_color"] == "red"
        assert entry["device_group"] == "mcu_like"
        assert entry["supports_bsp"] is True
        assert entry["supports_nviz"] is False
        assert "Slam" not in entry["sensors"]
        assert "Imu" in entry["sensors"]
        assert entry["imu_count"] == 1

    for name in ("Gina", "GF", "Hylla", "GS", "Glory"):
        entry = catalog[name]
        assert entry["device_color"] == "blue"
        assert entry["device_group"] == "ssh_nviz"
        assert entry["default_connection"] == "ssh"
        assert entry["supports_bsp"] is True
        assert entry["supports_nviz"] is True
        assert "Imu" in entry["sensors"]
        assert entry["imu_count"] == 2

    # Only Hylla is confirmed to have SLAM camera; Hylla has 1 IMU
    assert "Slam" in catalog["Hylla"]["sensors"]
    assert catalog["Hylla"]["imu_count"] == 1
    for name in ("Gina", "GF", "GS", "Glory"):
        assert "Slam" not in catalog[name]["sensors"]

    for name in ("Ada", "Charlie", "CORE", "Core Pro"):
        entry = catalog[name]
        assert entry["device_color"] == "unknown"
        assert entry["device_group"] == "ordinary_unknown"
        assert entry["supports_bsp"] is True
        assert entry["supports_nviz"] is False
        assert "Slam" not in entry["sensors"]
        assert "Imu" in entry["sensors"]
        assert entry["imu_count"] == 1

