#!/bin/sh
set -eu
mkdir -p /logs/verifier
if grep -qx hello /attempt/workspace/hello.txt; then
  printf '1\n' > /logs/verifier/reward.txt
else
  printf '0\n' > /logs/verifier/reward.txt
fi
