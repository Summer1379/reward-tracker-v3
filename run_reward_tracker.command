#!/bin/zsh
set -u

SCRIPT_DIR="${0:A:h}"
cd "$SCRIPT_DIR" || exit 1

for py in \
  /usr/local/bin/python3 \
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  /usr/local/bin/python3.13
do
  if [[ -x "$py" ]] && "$py" -c 'import tkinter' >/dev/null 2>&1; then
    exec "$py" "$SCRIPT_DIR/reward_tracker.py"
  fi
done

cat <<'EOF'
没有找到可用的 Tk Python。

请安装 python.org 的 macOS Python 3.13，或在终端运行：
  /usr/local/bin/python3 reward_tracker.py

不要使用 /usr/bin/python3：它会在当前 macOS/Tk 组合下崩溃。
不要使用 /opt/homebrew/bin/python3：它当前缺少 _tkinter。
EOF
exit 1
