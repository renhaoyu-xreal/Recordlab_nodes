#pragma once

#include "recordlab_nodes/device_adapters.h"

namespace recordlab::nodes::device_nodes::mcu {

class McuDeviceAdapter : public DeviceAdapter {
 public:
  std::string deviceType() const override { return "mcu"; }
  json check() override;
  json connect(const json &params) override;
  json init(const json &params) override;
  json start(const json &params) override;
  json stop() override;
  json release() override;
  json close() override;

 private:
  SerialExecutor executor_;
  bool connected_{false};
  bool initialized_{false};
  bool started_{false};
};

}  // namespace recordlab::nodes::device_nodes::mcu
