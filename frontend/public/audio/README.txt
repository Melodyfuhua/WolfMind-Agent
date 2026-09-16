把背景音乐 / 音效的 mp3 文件放到这个文件夹（frontend/public/audio/），文件名必须如下：

  day.mp3          白天背景音乐（建议 1~3 分钟，会自动循环播放）
  night.mp3        夜晚背景音乐（建议 1~3 分钟，会自动循环播放，紧张/低沉一些）
  wolf_kill.mp3    狼人刀人音效（短，1~3 秒；只有你是狼人时才会听到）
  hunter_shot.mp3  猎人开枪音效（短，枪声，1~2 秒）

说明：
- 文件名要完全一致（全小写、.mp3 后缀）。
- 放好后在浏览器里按 Ctrl+Shift+R 硬刷新即可生效，不用重启服务。
- 没放某个文件时，对应场景会自动回退到代码合成音（不会变哑）。
- 也可用 .ogg/.wav，但需要把 src/services/audio.js 里的扩展名改成对应格式；mp3 兼容性最好，推荐 mp3。

免费素材可去：Pixabay Music、Freesound、Mixkit、Free Music Archive 等搜
"werewolf / mystery / tension ambient"、"gunshot"、"horror sting" 之类关键词。
