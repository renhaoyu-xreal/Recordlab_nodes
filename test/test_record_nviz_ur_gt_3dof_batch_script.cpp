#include "recordlab_core/master_client.h"
#include "recordlab_master/master_server.h"
#include "recordlab_core/script_runner.h"
#include "recordlab_echo/echo.h"
#include "recordlab_echo/shm_ring_buffer.h"
#include "recordlab_system_nodes/recorder/recorder_node.h"

#include <cassert>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <thread>

int main() {
  namespace fs = std::filesystem;
  const fs::path root = fs::temp_directory_path() / "recordlab_nviz_ur_batch_contract";
  fs::remove_all(root);
  setenv("RECORDLAB_RECORD_ROOT", root.string().c_str(), 1);

  recordlab::MasterServer server(5860, 5861, 10000);
  server.start();
  recordlab::ScriptRunner runner("tcp://127.0.0.1:5860");
  assert(runner.start());
  recordlab::nodes::system_nodes::recorder::RecorderNode recorder("tcp://127.0.0.1:5860");
  assert(recorder.start());
  recordlab::MasterClient client("tcp://127.0.0.1:5860");

  client.registerNode({{"node", "/nviz_node"}, {"kind", "device_node"}});
  client.registerNode({{"node", "/ur_node"}, {"kind", "device_node"}});
  client.registerNode({{"node", "/localhost_node"}, {"kind", "tool_node"}});
  recordlab::ShmRingBuffer nviz_imu_ring;
  assert(nviz_imu_ring.create("/recordlab_test_nviz_imu", 16, 4096));
  client.registerPublisher({{"node", "/nviz_node"},
                            {"topic", "/nviz/imu"},
                            {"msg_type", "recordlab_msgs/ImuBatch"},
                            {"transport", {{"type", "shm_ring_buffer"},
                                            {"shm_name", "/recordlab_test_nviz_imu"},
                                            {"layout", "ring_buffer_v1"},
                                            {"slot_count", 16},
                                            {"slot_size", 4096}}}});

  auto ok_action = [](const recordlab::json &goal, std::function<void(const recordlab::json &)>,
                      std::atomic<bool> &) {
    return recordlab::json{{"success", true},
                           {"message", "ok"},
                           {"device_info", {{"label", "NVIZ"}, {"fsn", "FAKE_FSN"}}},
                           {"goal", goal}};
  };
  recordlab::ActionServer nviz_connect(ok_action);
  recordlab::ActionServer nviz_init(ok_action);
  recordlab::ActionServer nviz_start(ok_action);
  recordlab::ActionServer nviz_stop(ok_action);
  recordlab::ActionServer ur_move(ok_action);
  recordlab::ActionServer ur_execute([](const recordlab::json &goal, std::function<void(const recordlab::json &)>,
                                         std::atomic<bool> &) {
    std::this_thread::sleep_for(std::chrono::milliseconds(250));
    return recordlab::json{{"success", true}, {"message", "ok"}, {"goal", goal}};
  });
  client.registerAction({{"node", "/nviz_node"}, {"action", "/nviz/connect"}, {"endpoints", nviz_connect.descriptor()}});
  client.registerAction({{"node", "/nviz_node"}, {"action", "/nviz/init"}, {"endpoints", nviz_init.descriptor()}});
  client.registerAction({{"node", "/nviz_node"}, {"action", "/nviz/start"}, {"endpoints", nviz_start.descriptor()}});
  client.registerAction({{"node", "/nviz_node"}, {"action", "/nviz/stop"}, {"endpoints", nviz_stop.descriptor()}});
  client.registerAction({{"node", "/ur_node"}, {"action", "/ur/move_to_start"}, {"endpoints", ur_move.descriptor()}});
  client.registerAction({{"node", "/ur_node"}, {"action", "/ur/execute_trajectory"}, {"endpoints", ur_execute.descriptor()}});

  auto script_action = client.lookupAction("/script_runner/run_script")["data"]["endpoints"];
  recordlab::ActionClient script(script_action, 1000);
  auto goal = script.sendGoal({
      {"script_path", std::string(RECORDLAB_NODES_SOURCE_DIR) + "/scripts/record_nviz_ur_gt_3dof_batch.py"},
      {"args", recordlab::json::array({"--master", "tcp://127.0.0.1:5860",
                                        "--traj-list", "10-1",
                                        "--play-video", "0",
                                        "--tail-wait-s", "0"})},
      {"main_agent", "/nviz_node"}});
  auto result = script.waitForResult(goal, 10000);
  assert(result["data"]["success"] == true);
  assert(fs::exists(root));

  recorder.stop();
  runner.stop();
  server.stop();
  fs::remove_all(root);
  unsetenv("RECORDLAB_RECORD_ROOT");
  return 0;
}
