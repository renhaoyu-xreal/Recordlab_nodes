#pragma once

#include "recordlab_nodes/device_adapters.h"

namespace recordlab::nodes::device_nodes::nviz {

class NvizDeviceAdapter : public DeviceAdapter {
 public:
  std::string deviceType() const override { return "nviz"; }
  json check() override;
  json connect(const json &params) override;
  json init(const json &params) override;
  json start(const json &params) override;
  json stop() override;
  json release() override;
  json close() override;
  json deviceInfo() const override { return device_info_; }

 private:
  json runScript(const std::string &name, int timeout_ms = 60000);
  int64_t last_data_ms_{0};
  bool connected_{false};
  bool initialized_{false};
  bool started_{false};
  json device_info_ = json::object();
};

}  // namespace recordlab::nodes::device_nodes::nviz
