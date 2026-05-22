#pragma once

#include "recordlab_nodes/deviceNodes/nviz/nviz_device_adapter.h"
#include "recordlab_nodes/device_node_base.h"

namespace recordlab::nodes::deviceNodes::nviz {

class NvizNode : public DeviceNodeBase {
 public:
  explicit NvizNode(std::unique_ptr<DeviceAdapter> adapter = std::make_unique<NvizDeviceAdapter>(),
                    std::string endpoint = "tcp://127.0.0.1:5590");

 protected:
  void registerInterfaces() override;
};

}  // namespace recordlab::nodes::deviceNodes::nviz
