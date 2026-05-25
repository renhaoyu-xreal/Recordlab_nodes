#include "recordlab_xreal_runtime/xreal_bridge_client.h"

#include <cassert>
#include <chrono>
#include <cstdlib>
#include <fstream>
#include <string>
#include <sys/stat.h>
#include <thread>

int main() {
  const std::string worker = "/tmp/recordlab_fake_xreal_worker.py";
  {
    std::ofstream out(worker);
    out << "#!/usr/bin/env python3\n";
    out << R"PY(import json
import struct
import sys

MAGIC = b"RLCB"

def read_frame():
    prefix = sys.stdin.buffer.read(12)
    if len(prefix) != 12 or prefix[:4] != MAGIC:
        return None
    header_len, payload_len = struct.unpack("<II", prefix[4:])
    header = json.loads(sys.stdin.buffer.read(header_len).decode("utf-8"))
    sys.stdin.buffer.read(payload_len)
    return header

def write_frame(header, payload=b""):
    data = json.dumps(header, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(MAGIC + struct.pack("<II", len(data), len(payload)) + data + payload)
    sys.stdout.buffer.flush()

while True:
    header = read_frame()
    if not header:
        break
    req_id = header.get("id", "")
    action = header.get("action", "")
    if action == "enumerate_devices":
        result = {"success": True, "product_ids": [1082], "product_id": 1082, "device_count": 1}
    elif action == "get_glasses_state":
        result = {"success": True, "fsn": "FAKE_FSN", "has_rgb_sensor": True}
    elif action == "start_sensors":
        write_frame({"type": "event", "event": "imu_batch", "payload": {"items": [{"imu_idx": 0}]}})
        write_frame({"type": "event", "event": "camera", "payload": {"sensor": "rgb", "cams": [{"index": 0, "width": 1, "height": 1, "data_offset": 0, "data_size": 3}]}}, b"abc")
        result = {"success": True, "active_sensors": ["Imu", "Rgb"]}
    elif action == "shutdown":
        write_frame({"type": "response", "id": req_id, "result": {"success": True}})
        break
    else:
        result = {"success": True}
    write_frame({"type": "response", "id": req_id, "result": result})
)PY";
  }
  chmod(worker.c_str(), 0755);
  setenv("RECORDLAB_XREAL_PYTHON", worker.c_str(), 1);

  using recordlab::xreal_runtime::XrealBridgeClient;
  using recordlab::xreal_runtime::XrealBridgeCallbacks;

  bool saw_imu = false;
  bool saw_camera = false;
  XrealBridgeClient bridge("/tmp");
  bridge.setCallbacks(XrealBridgeCallbacks{
      [&](const recordlab::json &payload) { saw_imu = payload["items"].is_array(); },
      [&](const recordlab::json &metadata, const std::vector<uint8_t> &bytes) {
        saw_camera = metadata.value("sensor", "") == "rgb" && std::string(bytes.begin(), bytes.end()) == "abc";
      }});
  assert(bridge.enumerateDevices()["product_id"] == 1082);
  assert(bridge.createGlasses()["success"] == true);
  assert(bridge.openGlasses()["success"] == true);
  assert(bridge.getGlassesState()["fsn"] == "FAKE_FSN");
  assert(bridge.startSensors(0x07)["success"] == true);
  for (int i = 0; i < 20 && (!saw_imu || !saw_camera); ++i) {
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }
  assert(saw_imu);
  assert(saw_camera);
  bridge.shutdown();
  unsetenv("RECORDLAB_XREAL_PYTHON");
  return 0;
}
