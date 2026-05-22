#include "recordlab_nodes/device_adapters.h"

#include <chrono>
#include <cstdlib>
#include <filesystem>

namespace recordlab::nodes {

std::string toString(LifecycleState s) {
  switch (s) {
    case LifecycleState::Disconnected: return "disconnected";
    case LifecycleState::Connected: return "connected";
    case LifecycleState::Initialized: return "initialized";
    case LifecycleState::Started: return "started";
    case LifecycleState::Stopped: return "stopped";
    case LifecycleState::Released: return "released";
    case LifecycleState::Closed: return "closed";
    case LifecycleState::Error: return "error";
  }
  return "error";
}

SerialExecutor::SerialExecutor() : worker_(&SerialExecutor::loop, this) {}
SerialExecutor::~SerialExecutor() {
  running_ = false;
  cv_.notify_all();
  if (worker_.joinable()) worker_.join();
}

json SerialExecutor::run(const std::function<json()> &fn) {
  std::packaged_task<json()> task(fn);
  auto fut = task.get_future();
  {
    std::lock_guard<std::mutex> lock(mu_);
    tasks_.push(std::move(task));
  }
  cv_.notify_one();
  return fut.get();
}

void SerialExecutor::loop() {
  while (running_) {
    std::packaged_task<json()> task;
    {
      std::unique_lock<std::mutex> lock(mu_);
      cv_.wait(lock, [this] { return !running_ || !tasks_.empty(); });
      if (!running_ && tasks_.empty()) return;
      task = std::move(tasks_.front());
      tasks_.pop();
    }
    task();
  }
}

}  // namespace recordlab::nodes
