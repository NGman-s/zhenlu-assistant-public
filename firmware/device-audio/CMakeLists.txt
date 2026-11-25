cmake_minimum_required(VERSION 3.16)

# 诊录助手终端固件
# 目标：ESP32-S3-WROOM-1-N16R8（16 MB Flash + 8 MB PSRAM）
include($ENV{IDF_PATH}/tools/cmake/project.cmake)

# 生成 compile_commands.json，VS Code 的 C/C++ 智能提示靠它做精确索引
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

project(zhenlu)
