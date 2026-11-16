#!/bin/bash
ANSWER=/app/hello.txt
REWARD=/logs/verifier/reward.txt

if [ -f "$ANSWER" ] && grep -q '吴承恩' "$ANSWER"; then
  echo 1 > "$REWARD"
else
  echo 0 > "$REWARD"
fi
