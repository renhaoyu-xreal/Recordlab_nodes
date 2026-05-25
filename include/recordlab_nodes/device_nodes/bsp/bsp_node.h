#pragma once

#include "recordlab_echo/echo.h"
#include "recordlab_echo/shm_ring_buffer.h"
#include "recordlab_nodes/device_node_base.h"
#include "recordlab_nodes/device_nodes/bsp/bsp_device_adapter.h"

#include <atomic>
#include <thread>
#include <vector>

namespace recordlab::nodes::device_nodes::bsp {

class BspNode : public DeviceNodeBase {
 public:
  explicit BspNode(std::unique_ptr<DeviceAdapter> adapter = std::make_unique<BspDeviceAdapter>(),
                   std::string endpoint = "tcp://127.0.0.1:5590");
  ~BspNode() override;

 protected:
  void registerInterfaces() override;

 private:
  void healthLoop();
  void onImuBatch(const json &payload);
  void onCameraFrame(const json &metadata, const std::vector<uint8_t> &bytes);

  ShmRingBuffer imu_ring_;
  ShmRingBuffer rgb_ring_;
  ShmRingBuffer slam_ring_;
  std::atomic<bool> health_running_{false};
  std::thread health_thread_;
};

}  // namespace recordlab::nodes::device_nodes::bsp
