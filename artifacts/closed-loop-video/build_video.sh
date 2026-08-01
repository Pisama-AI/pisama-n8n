#!/usr/bin/env bash
set -euo pipefail

VIDEO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_VIDEO=(-c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -r 30)
COMMON_AUDIO=(-c:a aac -b:a 192k -ar 48000)

cd "$VIDEO_DIR"

ffmpeg -y -loglevel warning \
  -framerate 8 -i frames/n8n-live/frame-%05d.jpg -i narration-n8n.aiff \
  -filter_complex "[0:v]scale=1920:1080:flags=lanczos,fps=30,format=yuv420p[v];[1:a]loudnorm=I=-16:TP=-1.5:LRA=11,apad[a]" \
  -map "[v]" -map "[a]" -t 30 "${COMMON_VIDEO[@]}" "${COMMON_AUDIO[@]}" draft-n8n.mp4

ffmpeg -y -loglevel warning \
  -framerate 8 -i frames/pisama-live/frame-%05d.jpg -i narration-pisama.aiff \
  -filter_complex "[0:v]scale=1920:1080:flags=lanczos,fps=30,format=yuv420p[v];[1:a]atempo=1.033,loudnorm=I=-16:TP=-1.5:LRA=11,apad[a]" \
  -map "[v]" -map "[a]" -t 31 "${COMMON_VIDEO[@]}" "${COMMON_AUDIO[@]}" draft-pisama.mp4

ffmpeg -y -loglevel warning \
  -framerate 8 -i frames/revision-live/frame-%05d.jpg -i narration-revision.aiff \
  -filter_complex "[0:v]scale=1920:1080:flags=lanczos,fps=30,format=yuv420p[v];[1:a]loudnorm=I=-16:TP=-1.5:LRA=11,apad[a]" \
  -map "[v]" -map "[a]" -t 11 "${COMMON_VIDEO[@]}" "${COMMON_AUDIO[@]}" draft-revision.mp4

ffmpeg -y -loglevel warning -f concat -safe 0 -i concat-v1.txt -c copy closed-loop-demo-v1.mp4

mkdir -p assets/png
for svg in assets/*.svg; do
  png="assets/png/$(basename "${svg%.svg}").png"
  sips -s format png "$svg" --out "$png" >/dev/null
done

N8N_CURSOR_X="if(lt(t,3),520+(820-520)*t/3,if(lt(t,9),820,if(lt(t,10),820+(1185-820)*(t-9),if(lt(t,13),1185,if(lt(t,14),1185+(1460-1185)*(t-13),if(lt(t,21),1460,if(lt(t,22),1460+(1554-1460)*(t-21),if(lt(t,24),1554,if(lt(t,25),1554+(1185-1554)*(t-24),if(lt(t,28),1185,1460))))))))))"
N8N_CURSOR_Y="if(lt(t,3),260+(833-260)*t/3,if(lt(t,9),833,if(lt(t,10),833+(472-833)*(t-9),if(lt(t,13),472,if(lt(t,14),472+(88-472)*(t-13),if(lt(t,21),88,if(lt(t,22),88+(44-88)*(t-21),if(lt(t,24),44,if(lt(t,25),44+(692-44)*(t-24),if(lt(t,28),692,88))))))))))"

ffmpeg -y -loglevel warning \
  -i draft-n8n.mp4 \
  -loop 1 -i assets/png/label-n8n.png -loop 1 -i assets/png/tag-synthetic.png \
  -loop 1 -i assets/png/cursor.png -loop 1 -i assets/png/click.png \
  -loop 1 -i assets/png/caption-01.png -loop 1 -i assets/png/caption-02.png \
  -loop 1 -i assets/png/caption-03.png -loop 1 -i assets/png/caption-04.png \
  -loop 1 -i assets/png/caption-05.png \
  -filter_complex "[0:v][1:v]overlay=44:40[v1];[v1][2:v]overlay=1440:40[v2];[v2][3:v]overlay=x='${N8N_CURSOR_X}':y='${N8N_CURSOR_Y}'[v3];[v3][4:v]overlay=x='${N8N_CURSOR_X}-18':y='${N8N_CURSOR_Y}-18':enable='between(t,3.7,4.3)+between(t,9.7,10.4)+between(t,13.7,14.3)+between(t,21.7,22.3)+between(t,24.7,25.4)+between(t,27.7,28.3)'[v4];[v4][5:v]overlay=180:920:enable='between(t,0,5)'[v5];[v5][6:v]overlay=180:954:enable='between(t,5,10)'[v6];[v6][7:v]overlay=180:954:enable='between(t,10,16)'[v7];[v7][8:v]overlay=180:954:enable='between(t,16,23)'[v8];[v8][9:v]overlay=180:920:enable='between(t,23,30)'[v]" \
  -map "[v]" -map 0:a -t 30 -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p -c:a copy final-n8n.mp4

PISAMA_CURSOR_X="if(lt(t,4),500+(1156-500)*t/4,if(lt(t,10),1156,if(lt(t,16),1156+(470-1156)*(t-10)/6,if(lt(t,19),470,if(lt(t,20),470+(85-470)*(t-19),if(lt(t,25),85,1165))))))"
PISAMA_CURSOR_Y="if(lt(t,4),240+(400-240)*t/4,if(lt(t,10),400,if(lt(t,16),400+(665-400)*(t-10)/6,if(lt(t,19),665,if(lt(t,20),665+(162-665)*(t-19),if(lt(t,25),162,118))))))"

ffmpeg -y -loglevel warning \
  -i draft-pisama.mp4 \
  -loop 1 -i assets/png/label-pisama.png \
  -loop 1 -i assets/png/tag-synthetic.png -loop 1 -i assets/png/tag-release.png \
  -loop 1 -i assets/png/cursor.png -loop 1 -i assets/png/click.png \
  -loop 1 -i assets/png/caption-06.png -loop 1 -i assets/png/caption-07.png \
  -loop 1 -i assets/png/caption-08.png -loop 1 -i assets/png/caption-09.png \
  -loop 1 -i assets/png/caption-10.png \
  -filter_complex "[0:v][1:v]overlay=44:40[v1];[v1][2:v]overlay=1440:40:enable='between(t,0,20)'[v2];[v2][3:v]overlay=1420:40:enable='between(t,20,31)'[v3];[v3][4:v]overlay=x='${PISAMA_CURSOR_X}':y='${PISAMA_CURSOR_Y}'[v4];[v4][5:v]overlay=x='${PISAMA_CURSOR_X}-18':y='${PISAMA_CURSOR_Y}-18':enable='between(t,4.6,5.2)+between(t,16.4,17.1)+between(t,19.4,20.1)+between(t,24.4,25.1)'[v5];[v5][6:v]overlay=180:954:enable='between(t,0,6)'[v6];[v6][7:v]overlay=180:954:enable='between(t,6,13)'[v7];[v7][8:v]overlay=180:954:enable='between(t,13,19)'[v8];[v8][9:v]overlay=180:954:enable='between(t,19,25)'[v9];[v9][10:v]overlay=180:920:enable='between(t,25,31)'[v]" \
  -map "[v]" -map 0:a -t 31 -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p -c:a copy final-pisama.mp4

REVISION_CURSOR_X="if(lt(t,3.5),650+(1205-650)*t/3.5,1205)"
REVISION_CURSOR_Y="if(lt(t,3.5),260+(646-260)*t/3.5,646)"

ffmpeg -y -loglevel warning \
  -i draft-revision.mp4 \
  -loop 1 -i assets/png/label-revision.png -loop 1 -i assets/png/tag-release.png \
  -loop 1 -i assets/png/cursor.png -loop 1 -i assets/png/click.png \
  -loop 1 -i assets/png/caption-11.png -loop 1 -i assets/png/caption-12.png \
  -filter_complex "[0:v][1:v]overlay=44:40[v1];[v1][2:v]overlay=1420:40[v2];[v2][3:v]overlay=x='${REVISION_CURSOR_X}':y='${REVISION_CURSOR_Y}'[v3];[v3][4:v]overlay=x='${REVISION_CURSOR_X}-18':y='${REVISION_CURSOR_Y}-18':enable='between(t,3.6,4.3)'[v4];[v4][5:v]overlay=180:954:enable='between(t,0,6)'[v5];[v5][6:v]overlay=180:920:enable='between(t,6,11)'[v]" \
  -map "[v]" -map 0:a -t 11 -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p -c:a copy final-revision.mp4

ffmpeg -y -loglevel warning -f concat -safe 0 -i concat-final.txt -c copy closed-loop-demo.mp4
