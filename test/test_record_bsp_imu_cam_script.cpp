#include "recordlab_master/master_server.h"
#include "recordlab_core/master_client.h"
#include "recordlab_core/script_runner.h"
#include "recordlab_echo/echo.h"
#include "recordlab_nodes/device_nodes/bsp/bsp_node.h"
#include "recordlab_system_nodes/recorder/recorder_node.h"

#include <cassert>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <thread>

int main() {
  namespace fs = std::filesystem;
  const fs::path root = fs::temp_directory_path() / "recordlab_bsp_script_contract";
  fs::remove_all(root);
  setenv("RECORDLAB_RECORD_ROOT", root.string().c_str(), 1);
  setenv("RECORDLAB_LSUSB_OUTPUT", "Bus 001 Device 002: ID 3318:043a XREAL Hylla\n", 1);
  setenv("RECORDLAB_BSP_SDK_PROBE_JSON",
         "{\"success\":true,\"product_ids\":[1082],\"product_id\":1082,\"device_count\":1,\"fsn\":\"SCRIPT_FSN\"}",
         1);

  recordlab::MasterServer server(5850, 5851, 1000);
  server.start();

  recordlab::ScriptRunner runner("tcp://127.0.0.1:5850");
  assert(runner.start());

  recordlab::nodes::device_nodes::bsp::BspNode bsp(
      std::make_unique<recordlab::nodes::device_nodes::bsp::BspDeviceAdapter>(),
      "tcp://127.0.0.1:5850");
  assert(bsp.start());
  recordlab::nodes::system_nodes::recorder::RecorderNode recorder("tcp://127.0.0.1:5850");
  assert(recorder.start());

  recordlab::MasterClient client("tcp://127.0.0.1:5850");
  auto action = client.lookupAction("/script_runner/run_script")["data"]["endpoints"];
  recordlab::ActionClient script(action, 1000);
  auto goal = script.sendGoal({
      {"script_path", std::string(RECORDLAB_NODES_SOURCE_DIR) + "/scripts/record_bsp_imu_cam.py"},
      {"args", recordlab::json::array({"--master", "tcp://127.0.0.1:5850",
                                        "--experiment-keyword", "contract",
                                        "--recorder-name", "tester",
                                        "--duration", "0.2"})},
      {"main_agent", "/bsp_node"}});
  auto result = script.waitForResult(goal, 10000);
  assert(result["data"]["success"] == true);

  fs::path parent = root / "free_record/imu_and_cam";
  assert(fs::exists(parent));
  int dataset_count = 0;
  for (const auto &entry : fs::directory_iterator(parent)) {
    if (!entry.is_directory()) continue;
    ++dataset_count;
    assert(fs::exists(entry.path() / "record_request.json"));
    assert(fs::exists(entry.path() / "record_info.txt"));
    assert(fs::exists(entry.path() / "topics.json"));
  }
  assert(dataset_count == 1);

  recorder.stop();
  bsp.stop();
  runner.stop();
  server.stop();
  fs::remove_all(root);
  unsetenv("RECORDLAB_RECORD_ROOT");
  unsetenv("RECORDLAB_LSUSB_OUTPUT");
  unsetenv("RECORDLAB_BSP_SDK_PROBE_JSON");
  return 0;
}
