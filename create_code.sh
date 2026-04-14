#!/bin/bash
# 用于实现将代码打包成md给大模型 analysis的工具
# 获取脚本所在的绝对路径
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
FILE="${SCRIPT_DIR}"/free-node-collector.md
COMMAND="${SCRIPT_DIR}"/code2prompt
echo "脚本目录: ${SCRIPT_DIR}"
if [ -f "${FILE}" ]; then
  rm -rf "${FILE}"
fi

$COMMAND -i "*.py,*.yaml,*.yml,*.txt" -e ".venv/*,dist/*" -O "${FILE}"
