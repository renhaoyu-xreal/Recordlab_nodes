#pragma once

#include "recordlab_nodes/deviceNodes/bsp/bsp_device_adapter.h"
#include "recordlab_nodes/device_node_base.h"

namespace recordlab::nodes::deviceNodes::bsp {

class BspNode : public DeviceNodeBase {
 public:
  explicit BspNode(std::unique_ptr<DeviceAdapter> adapter = std::make_unique<BspDeviceAdapter>(),
                   std::string endpoint = "tcp://127.0.0.1:5590");

 protected:
  void registerInterfaces() override;
};

}  // namespace recordlab::nodes::deviceNodes::bsp
