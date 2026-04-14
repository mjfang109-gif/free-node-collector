#!/bin/bash

# 给一点缓冲时间，确保文件挂载就绪
sleep 2

echo "🚀 容器初始化：进行首次画面渲染..."
# 读取挂载进来的 top_node.json 和 live.html，生成 bg.jpg
python3 render.py

# 开启后台循环：每隔 15 分钟（900秒）重新渲染一次画面
(
  while true; do
    sleep 900
    echo "🔄 定时更新：重新读取宿主机文件进行渲染..."
    python3 render.py
  done
) &

# 前台主进程：FFmpeg 推流
echo "🎥 启动 FFmpeg 推送至 YouTube..."
ffmpeg -stream_loop -1 -re -loop 1 -update 1 -i bg.jpg -stream_loop -1 -i bgm.mp3 \
-vf "drawtext=fontfile=/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc:text='%{localtime\:%H\\:%M\\:%S}':x=1560:y=65:fontsize=56:fontcolor=white:letter_spacing=2" \
-c:v libx264 -preset veryfast -r 15 -b:v 800k -maxrate 800k -bufsize 1600k \
-c:a aac -b:a 128k -ar 44100 \
-f flv "rtmp://a.rtmp.youtube.com/live2/${YOUTUBE_STREAM_KEY}"