import { useEffect, useRef } from "react";
import { useVideoDubStore } from "./store";
import { TrackKind } from "./types";

/** 由本组件驱动播放的三条音轨（原音走 <video> 自带声音，不在其列）。 */
const PLAYED_KINDS: TrackKind[] = ["dubbing", "bgm", "sfx"];

/**
 * 音轨播放引擎：以视频播放进度为时钟，让配音 / 背景音乐 / 音效轨上
 * 带有 url 的片段同步出声；轨道被喇叭静音或片段不在指针范围内时暂停。
 * 渲染为空，仅挂载 <audio> 元素池。
 */
export function TrackAudioPlayer() {
  const playing = useVideoDubStore((state) => state.playing);
  const clips = useVideoDubStore((state) => PLAYED_KINDS.flatMap((kind) => state.clips[kind]));
  const audioMapRef = useRef<Map<string, HTMLAudioElement>>(new Map());

  // 维护音频元素池：片段增删时同步创建 / 释放
  useEffect(() => {
    const map = audioMapRef.current;
    const wanted = new Set(clips.filter((clip) => clip.url).map((clip) => clip.id));
    for (const [id, audio] of map) {
      if (!wanted.has(id)) {
        audio.pause();
        audio.remove();
        map.delete(id);
      }
    }
    clips.forEach((clip) => {
      if (!clip.url || map.has(clip.id)) return;
      const audio = new Audio(clip.url);
      audio.preload = "auto";
      audio.dataset.trackClip = clip.id;
      audio.dataset.trackName = clip.name;
      audio.style.display = "none";
      document.body.appendChild(audio);
      map.set(clip.id, audio);
    });
  }, [clips]);

  // 播放中逐帧对齐：进入片段范围即起播，漂移超阈值则重同步；变速片段按倍率换算进度
  useEffect(() => {
    const map = audioMapRef.current;
    if (!playing) {
      map.forEach((audio) => {
        audio.pause();
        if (audio.playbackRate !== 1) audio.playbackRate = 1;
      });
      return;
    }
    let frame = 0;
    const tick = () => {
      const state = useVideoDubStore.getState();
      const time = state.currentTime;
      for (const kind of PLAYED_KINDS) {
        const muted = state.mutedTracks[kind];
        for (const clip of state.clips[kind]) {
          const audio = map.get(clip.id);
          if (!audio) continue;
          const speed = clip.speed && clip.speed > 0 ? clip.speed : 1;
          const active = Boolean(clip.url) && !muted && time >= clip.start && time < clip.start + clip.duration;
          if (active) {
            if (audio.playbackRate !== speed) audio.playbackRate = speed;
            const target = Math.max(0, (time - clip.start) * speed);
            if (audio.paused) {
              try {
                audio.currentTime = target;
              } catch {
                /* 尚未加载出可播放范围时忽略 */
              }
              void audio.play().catch(() => {});
            } else if (Math.abs(audio.currentTime - target) > 0.25) {
              try {
                audio.currentTime = target;
              } catch {
                /* 同上 */
              }
            }
          } else {
            if (!audio.paused) audio.pause();
            if (audio.playbackRate !== 1) audio.playbackRate = 1;
          }
        }
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing]);

  return null;
}
