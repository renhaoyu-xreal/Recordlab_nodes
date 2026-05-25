#include "recordlab_nodes/device_nodes/bsp/bsp_node.h"
#include <chrono>
#include <iostream>
#include <thread>
int main() {
  recordlab::nodes::device_nodes::bsp::BspNode node;
  if (!node.start()) return 1;
  std::cout << "bsp_node running\n";
  while (true) std::this_thread::sleep_for(std::chrono::seconds(1));
}
