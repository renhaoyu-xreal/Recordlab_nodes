#pragma once

#include "recordlab_master/registries.h"

#include <atomic>
#include <condition_variable>
#include <functional>
#include <future>
#include <mutex>
#include <queue>
#include <string>
#include <thread>

namespace recordlab::nodes {

enum class LifecycleState { Disconnected, Connected, Initialized, Started, Stopped, Released, Closed, Error };

std::string toString(LifecycleState s);

class SerialExecutor {
 public:
  SerialExecutor();
  ~SerialExecutor();
  json run(const std::function<json()> &fn);

 private:
  void loop();
  std::atomic<bool> running_{true};
  std::mutex mu_;
  std::condition_variable cv_;
  std::queue<std::packaged_task<json()>> tasks_;
  std::thread worker_;
};

class DeviceAdapter {
 public:
  virtual ~DeviceAdapter() = default;
  virtual std::string deviceType() const = 0;
  virtual json check() = 0;
  virtual json connect(const json &params) = 0;
  virtual json init(const json &params) = 0;
  virtual json start(const json &params) = 0;
  virtual json stop() = 0;
  virtual json release() = 0;
  virtual json close() = 0;
  virtual json deviceInfo() const { return json::object(); }
};

class SimulatedDeviceAdapter : public DeviceAdapter {
 public:
  explicit SimulatedDeviceAdapter(std::string type) : type_(std::move(type)) {}
  std::string deviceType() const override { return type_; }
  json check() override { return {{"success", true}, {"message", type_ + " simulated ok"}}; }
  json connect(const json &) override { return ok("connected"); }
  json init(const json &) override { return ok("initialized"); }
  json start(const json &) override { return ok("started"); }
  json stop() override { return ok("stopped"); }
  json release() override { return ok("released"); }
  json close() override { return ok("closed"); }

 private:
  json ok(const std::string &state) { return {{"success", true}, {"state", state}, {"device_type", type_}}; }
  std::string type_;
};

}  // namespace recordlab::nodes
