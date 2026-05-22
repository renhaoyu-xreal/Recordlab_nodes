#include "recordlab_nodes/health_monitor.h"
#include <chrono>
#include <iostream>
#include <thread>
int main() {
  recordlab::nodes::HealthMonitor node;
  if (!node.start()) return 1;
  std::cout << "health_monitor running\n";
  while (true) std::this_thread::sleep_for(std::chrono::seconds(1));
}
