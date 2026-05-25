#pragma once

#include "recordlab_nodes/device_adapters.h"
#include "recordlab_xreal_runtime/xreal_bridge_client.h"

#include <memory>

namespace recordlab::nodes::device_nodes::bsp {

class BspDeviceAdapter : public DeviceAdapter {
 public:
  std::string deviceType() const override { return "bsp"; }
  json check() override;
  json connect(const json &params) override;
  json init(const json &params) override;
  json start(const json &params) override;
  json stop() override;
  json release() override;
  json close() override;
  json deviceInfo() const override;
  void setStreamCallbacks(xreal_runtime::XrealBridgeCallbacks callbacks);
  std::string initStrategy() const { return init_strategy_; }
  std::string startStrategy() const { return start_strategy_; }

 private:
  json runCheck();
  std::string readLsusbOutput() const;
  void updateStrategiesFromDevice();

  SerialExecutor executor_;
  bool connected_{false};
  bool initialized_{false};
  bool started_{false};
  json device_info_ = json::object();
  std::string init_strategy_{"generic_bsp"};
  std::string start_strategy_{"generic_bsp"};
  std::unique_ptr<xreal_runtime::XrealBridgeClient> bridge_;
};

}  // namespace recordlab::nodes::device_nodes::bsp
