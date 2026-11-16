#!/bin/bash
ANSWER=/app/hello.txt
REWARD=/logs/verifier/reward.txt

if [ -f "$ANSWER" ] && grep -Eq '500|五百年' "$ANSWER"; then
  echo 1 > "$REWARD"
else
  echo 0 > "$REWARD"
fi
