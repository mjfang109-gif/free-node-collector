#!/bin/bash

# 确保环境完全就绪
sleep 2

echo "🚀 容器初始化：进行首次画面渲染..."
python3 render.py

# 后台定时刷新渲染
(
  while true; do
    sleep 900
    echo "🔄 定时更新：重新渲染画面..."
    python3 render.py
  done
) &

echo "🎥 启动 FFmpeg 推送至 YouTube..."

# 【终极解决方案】：
# 1. 使用单引号包裹 -vf 后的整个内容，防止 Bash 干扰
# 2. 针对 FFmpeg 4.4.2，localtime 后的冒号需要一层转义，时间内部的冒号需要两层转
ffmpeg -re \
    -loop 1 -i /app/bg.jpg \
    -stream_loop -1 -i /app/bgm.mp3 \
    -vf "drawtext=fontfile=/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc:text='%{localtime\:%T}':x=1550:y=90:fontsize=45:fontcolor=white:shadowcolor=black:shadowx=2:shadowy=2" \
    -c:v libx264 -preset veryfast -r 15 -g 30 \
    -b:v 2500k -maxrate 2500k -bufsize 5000k \
    -c:a aac -b:a 128k -ar 44100 \
    -f flv "rtmp://a.rtmp.youtube.com/live2/${YOUTUBE_STREAM_KEY}"