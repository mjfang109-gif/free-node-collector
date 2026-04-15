#!/bin/bash

# 确保环境完全就绪
sleep 2

echo "🚀 容器初始化：进行首次画面渲染..."
# 此时生成的路径是 /app/bg.jpg
python3 render.py

# 开启后台循环：每隔 15 分钟重新渲染一次
(
  while true; do
    sleep 900
    echo "🔄 定时更新：重新渲染画面..."
    python3 render.py
  done
) &

echo "🎥 启动 FFmpeg 推送至 YouTube..."

# 【核心修正】:
# 1. -f image2 必须紧跟 -update 1，中间不能插入 -stream_loop
# 2. 对于单张图片更新流，-update 1 已经包含了循环读取逻辑，第一个输入不需要 -stream_loop
ffmpeg -re \
    -loop 1 -i /app/bg.jpg \
    -stream_loop -1 -i /app/bgm.mp3 \
    -vf "drawtext=fontfile=/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc:text='%{localtime\:%H\\:%M\\:%S}':x=1560:y=65:fontsize=56:fontcolor=white:shadowcolor=black:shadowx=2:shadowy=2" \
    -c:v libx264 -preset veryfast -r 15 -g 30 -b:v 800k -maxrate 800k -bufsize 1600k \
    -c:a aac -b:a 128k -ar 44100 \
    -shortest -f flv "rtmp://a.rtmp.youtube.com/live2/${YOUTUBE_STREAM_KEY}"