#pragma once

#include "recordlab_echo/echo.h"
#include "recordlab_echo/shm_ring_buffer.h"
#include "recordlab_nodes/device_node_base.h"
#include "recordlab_nodes/device_nodes/nviz/nviz_device_adapter.h"

#include <memory>

namespace recordlab::nodes::device_nodes::nviz {

class NvizNode : public DeviceNodeBase {
 public:
  explicit NvizNode(std::unique_ptr<DeviceAdapter> adapter = std::make_unique<NvizDeviceAdapter>(),
                    std::string endpoint = "tcp://127.0.0.1:5590");

 protected:
  void registerInterfaces() override;

 private:
  ShmRingBuffer imu_ring_;
};

}  // namespace recordlab::nodes::device_nodes::nviz
