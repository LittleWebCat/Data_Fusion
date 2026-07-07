#!/usr/bin/env bash
set -e
RUN=${1:-$(cat "$HOME/Downloads/latest_camera_dataset.txt")}
OUT=${2:-$RUN/sixcam_grid.mp4}

ffmpeg -y -hide_banner \
  -fflags +genpts -i "$RUN/CAM_FRONT_LEFT/video.mkv" \
  -fflags +genpts -i "$RUN/CAM_FRONT/video.mkv" \
  -fflags +genpts -i "$RUN/CAM_FRONT_RIGHT/video.mkv" \
  -fflags +genpts -i "$RUN/CAM_BACK_RIGHT/video.mkv" \
  -fflags +genpts -i "$RUN/CAM_BACK/video.mkv" \
  -fflags +genpts -i "$RUN/CAM_BACK_LEFT/video.mkv" \
  -filter_complex "\
[0:v]trim=start_frame=5,setpts=PTS-STARTPTS,scale=640:480,drawtext=text='CAM_FRONT':x=15:y=20:fontsize=28:fontcolor=white:box=1:boxcolor=black@0.6[v0];\
[1:v]trim=start_frame=5,setpts=PTS-STARTPTS,scale=640:480,drawtext=text='CAM_FRONT_LEFT':x=15:y=20:fontsize=28:fontcolor=white:box=1:boxcolor=black@0.6[v1];\
[2:v]trim=start_frame=5,setpts=PTS-STARTPTS,scale=640:480,drawtext=text='CAM_FRONT_RIGHT':x=15:y=20:fontsize=28:fontcolor=white:box=1:boxcolor=black@0.6[v2];\
[3:v]trim=start_frame=5,setpts=PTS-STARTPTS,scale=640:480,drawtext=text='CAM_BACK':x=15:y=20:fontsize=28:fontcolor=white:box=1:boxcolor=black@0.6[v3];\
[4:v]trim=start_frame=5,setpts=PTS-STARTPTS,scale=640:480,drawtext=text='CAM_BACK_LEFT':x=15:y=20:fontsize=28:fontcolor=white:box=1:boxcolor=black@0.6[v4];\
[5:v]trim=start_frame=5,setpts=PTS-STARTPTS,scale=640:480,drawtext=text='CAM_BACK_RIGHT':x=15:y=20:fontsize=28:fontcolor=white:box=1:boxcolor=black@0.6[v5];\
[v0][v1][v2][v3][v4][v5]xstack=inputs=6:layout=0_0|640_0|1280_0|0_480|640_480|1280_480,format=yuv420p[out]" \
  -map "[out]" -r 15 -c:v libx264 -preset veryfast -crf 20 "$OUT"

echo "Saved: $OUT"
