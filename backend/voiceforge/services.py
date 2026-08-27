import json
import os
import subprocess
import uuid
import wave
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from backend.llm.llm_client import LLMClient
from backend.tts.tts_factory import get_tts_engine
from backend.voiceforge.database import session, storage_root
from backend.voiceforge.storage import ensure_project_dirs, resolve_storage_key


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def update_task(task_id: str, status: str, progress: float, error_message: str = None, output: dict = None):
    fields = ["status = ?", "progress = ?"]
    values = [status, progress]
    if status == "running":
        fields.append("started_at = ?")
        values.append(utc_now())
    if status in {"succeeded", "failed", "cancelled"}:
        fields.append("finished_at = ?")
        values.append(utc_now())
    if error_message is not None:
        fields.append("error_message = ?")
        values.append(error_message)
    if output is not None:
        fields.append("output_json = ?")
        values.append(json.dumps(output, ensure_ascii=False))
    values.append(task_id)
    with session() as conn:
        condition = " AND status != 'cancelled'" if status == "running" else ""
        conn.execute(f"UPDATE vf_tasks SET {', '.join(fields)} WHERE id = ?{condition}", values)


def audio_duration(path: Path):
    if path.suffix.lower() == ".wav":
        with wave.open(str(path), "rb") as stream:
            return stream.getnframes() / max(stream.getframerate(), 1)
    try:
        completed = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
        return float(completed.stdout.strip())
    except Exception:
        return None


def task_is_active(conn, task_id: str, project_id: str):
    row = conn.execute(
        "SELECT t.status FROM vf_tasks t JOIN vf_projects p ON p.id = t.project_id WHERE t.id = ? AND p.id = ?",
        (task_id, project_id),
    ).fetchone()
    return bool(row and row["status"] not in {"cancelled", "failed"})


def synthesize_sentence(sentence_id: str, task_id: str, expected_version: int | None = None, interface_id: str | None = None):
    update_task(task_id, "running", 0.1)
    try:
        with session() as conn:
            row = conn.execute(
                """
                SELECT s.*, p.default_interface_id, p.default_voice_id, p.default_speed,
                       v.interface_id AS profile_interface_id, v.voice_id AS profile_voice_id, v.mode,
                       v.reference_storage_key, v.params_json
                FROM vf_sentences s JOIN vf_projects p ON p.id = s.project_id
                LEFT JOIN vf_voices v ON v.id = s.voice_profile_id WHERE s.id = ?
                """,
                (sentence_id,),
            ).fetchone()
            if not row:
                return
            data = dict(row)
            if not task_is_active(conn, task_id, data["project_id"]):
                return
            if expected_version is not None and data["version"] != expected_version:
                update_task(task_id, "cancelled", 1, error_message="句子已更新，已取消过期合成任务")
                return
            conn.execute("UPDATE vf_sentences SET status = 'generating', error_message = NULL WHERE id = ? AND version = ?", (sentence_id, data["version"]))
        text = (data.get("edited_text") or data["text"]).strip()
        # 显式传入的 interface_id 优先级最高，其次句子/声音档案/项目默认，最后回退 edge_tts
        effective_interface_id = interface_id or data.get("interface_id") or data.get("profile_interface_id") or data.get("default_interface_id") or "edge_tts"
        voice_id = data.get("voice_id") or data.get("profile_voice_id") or data.get("default_voice_id")
        output_key = f"projects/{data['project_id']}/audio/{sentence_id}.wav"
        output_path = storage_root() / "temp" / f"{task_id}.wav"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not text:
            with wave.open(str(output_path), "wb") as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(16000)
                stream.writeframes(b"\x00\x00" * 1600)
        else:
            params = json.loads(data.get("params_json") or "{}")
            ref_path = resolve_storage_key(data["reference_storage_key"]) if data.get("reference_storage_key") else None
            engine = get_tts_engine(effective_interface_id)
            succeeded = engine.synthesize(
                text,
                str(output_path),
                ref_audio=str(ref_path) if ref_path else None,
                mode=data.get("mode"),
                speed=data.get("speed") or data.get("default_speed"),
                voice=voice_id,
                voice_design=params.get("voice_design"),
                controllable_clone=params.get("controllable_clone"),
                ref_text=params.get("ref_text"),
            )
            if not succeeded or not output_path.exists() or output_path.stat().st_size == 0:
                raise RuntimeError("TTS 接口未返回有效音频")
        duration = audio_duration(output_path)
        with session() as conn:
            if not task_is_active(conn, task_id, data["project_id"]):
                output_path.unlink(missing_ok=True)
                return
            if expected_version is not None:
                current = conn.execute("SELECT version FROM vf_sentences WHERE id = ?", (sentence_id,)).fetchone()
                if not current or current["version"] != expected_version:
                    output_path.unlink(missing_ok=True)
                    update_task(task_id, "cancelled", 1, error_message="句子已更新，已取消过期合成任务")
                    return
            final_path = resolve_storage_key(output_key)
            final_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(output_path), str(final_path))
            conn.execute(
                "UPDATE vf_sentences SET status = 'done', audio_storage_key = ?, audio_duration = ?, task_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (output_key, duration, task_id, sentence_id),
            )
        update_task(task_id, "succeeded", 1, output={"sentence_id": sentence_id, "storage_key": output_key, "duration": duration})
    except Exception as exc:
        output_path = storage_root() / "temp" / f"{task_id}.wav"
        output_path.unlink(missing_ok=True)
        with session() as conn:
            if conn.execute("SELECT id FROM vf_sentences WHERE id = ?", (sentence_id,)).fetchone():
                if expected_version is None:
                    conn.execute("UPDATE vf_sentences SET status = 'error', error_message = ? WHERE id = ?", (str(exc), sentence_id))
                else:
                    conn.execute(
                        "UPDATE vf_sentences SET status = 'error', error_message = ? WHERE id = ? AND version = ?",
                        (str(exc), sentence_id, expected_version),
                    )
        update_task(task_id, "failed", 1, error_message=str(exc))
        raise


def merge_project_audio(project_id: str, task_id: str, chapter_id: str = None, output_format: str = "wav", gap_seconds: float = 0):
    update_task(task_id, "running", 0.1)
    try:
        with session() as conn:
            if not task_is_active(conn, task_id, project_id):
                return
            sql = "SELECT order_index, audio_storage_key, pause_after FROM vf_sentences WHERE project_id = ? AND status = 'done' AND audio_storage_key IS NOT NULL"
            params = [project_id]
            if chapter_id:
                sql += " AND chapter_id = ?"
                params.append(chapter_id)
            rows = conn.execute(sql + " ORDER BY order_index", params).fetchall()
        if not rows:
            raise ValueError("项目没有已完成音频")
        inputs = [resolve_storage_key(row["audio_storage_key"]) for row in rows]
        if any(not path.exists() for path in inputs):
            raise ValueError("存在缺失的句子音频")
        temp_dir = storage_root() / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        output = temp_dir / f"{task_id}-merged.wav"
        if all(path.suffix.lower() == ".wav" for path in inputs):
            with wave.open(str(inputs[0]), "rb") as first:
                params = first.getparams()
                frames = [first.readframes(first.getnframes())]
            for path in inputs[1:]:
                with wave.open(str(path), "rb") as stream:
                    if stream.getparams()[:3] != params[:3]:
                        raise ValueError("句子音频格式不一致，无法直接合并")
                    frames.append(stream.readframes(stream.getnframes()))
            with wave.open(str(output), "wb") as target:
                target.setparams(params)
                for index, frame in enumerate(frames):
                    target.writeframes(frame)
                    if index < len(rows) - 1:
                        pause = max(float(rows[index]["pause_after"] or 0), gap_seconds)
                        target.writeframes(b"\x00" * int(pause * params.framerate * params.nchannels * params.sampwidth))
        else:
            if not shutil.which("ffmpeg"):
                raise ValueError("FFmpeg 不可用，无法合并非 WAV 音频")
            manifest = temp_dir / f"{task_id}-concat.txt"
            manifest.write_text("\n".join(f"file '{path.as_posix()}'" for path in inputs), encoding="utf-8")
            subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(manifest), "-c", "copy", str(output)], check=True, capture_output=True, timeout=300)
            manifest.unlink(missing_ok=True)
        if output_format not in {"wav", "mp3", "flac"}:
            raise ValueError("不支持的导出格式")
        converted = output
        if output_format != "wav":
            if not shutil.which("ffmpeg"):
                raise ValueError("FFmpeg 不可用，无法转码导出")
            converted = temp_dir / f"{task_id}-merged.{output_format}"
            subprocess.run(["ffmpeg", "-y", "-i", str(output), str(converted)], check=True, capture_output=True, timeout=300)
            output.unlink(missing_ok=True)
        output_key = f"projects/{project_id}/exports/{converted.name}"
        with session() as conn:
            if not task_is_active(conn, task_id, project_id):
                output.unlink(missing_ok=True)
                return
            project_dir = ensure_project_dirs(project_id)
            final_output = project_dir / "exports" / f"{task_id}-merged.{output_format}"
            shutil.move(str(converted), str(final_output))
            output_key = f"projects/{project_id}/exports/{final_output.name}"
            conn.execute("INSERT INTO vf_exports (id, project_id, export_type, storage_key, file_name, status, task_id, format) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (uuid.uuid4().hex, project_id, "merged_audio", output_key, final_output.name, "succeeded", task_id, output_format))
        update_task(task_id, "succeeded", 1, output={"storage_key": output_key})
    except Exception as exc:
        for suffix in ("wav", "mp3", "flac"):
            (storage_root() / "temp" / f"{task_id}-merged.{suffix}").unlink(missing_ok=True)
        update_task(task_id, "failed", 1, error_message=str(exc))
        raise


def export_project_srt(project_id: str, task_id: str, chapter_id: str = None):
    update_task(task_id, "running", 0.1)
    try:
        with session() as conn:
            sql = "SELECT text, edited_text, audio_duration, pause_after FROM vf_sentences WHERE project_id = ? AND status = 'done'"
            params = [project_id]
            if chapter_id:
                sql += " AND chapter_id = ?"
                params.append(chapter_id)
            sql += " ORDER BY order_index"
            rows = conn.execute(sql, params).fetchall()
        if not rows:
            raise ValueError("没有已完成的句子音频")
        def stamp(seconds):
            milliseconds = int(seconds * 1000); hours, milliseconds = divmod(milliseconds, 3600000); minutes, milliseconds = divmod(milliseconds, 60000); seconds, milliseconds = divmod(milliseconds, 1000)
            return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"
        cursor, lines = 0.0, []
        for index, row in enumerate(rows, 1):
            end = cursor + float(row["audio_duration"] or 0)
            lines.extend([str(index), f"{stamp(cursor)} --> {stamp(end)}", row["edited_text"] or row["text"], ""])
            cursor = end + float(row["pause_after"] or 0)
        key = f"projects/{project_id}/exports/{task_id}.srt"; path = resolve_storage_key(key); path.parent.mkdir(parents=True, exist_ok=True); path.write_text("\n".join(lines), encoding="utf-8")
        with session() as conn:
            conn.execute("INSERT INTO vf_exports (id, project_id, export_type, storage_key, file_name, status, task_id, format) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (uuid.uuid4().hex, project_id, "srt", key, path.name, "succeeded", task_id, "srt"))
        update_task(task_id, "succeeded", 1, output={"storage_key": key})
    except Exception as exc:
        update_task(task_id, "failed", 1, error_message=str(exc)); raise


def export_sentence_archive(project_id: str, task_id: str, chapter_id: str = None):
    update_task(task_id, "running", 0.1)
    try:
        with session() as conn:
            sql = "SELECT order_index, audio_storage_key FROM vf_sentences WHERE project_id = ? AND status = 'done' AND audio_storage_key IS NOT NULL"
            params = [project_id]
            if chapter_id:
                sql += " AND chapter_id = ?"
                params.append(chapter_id)
            sql += " ORDER BY order_index"
            rows = conn.execute(sql, params).fetchall()
        if not rows:
            raise ValueError("没有可导出的句子音频")
        key = f"projects/{project_id}/exports/{task_id}-sentences.zip"; path = resolve_storage_key(key); path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for index, row in enumerate(rows, 1):
                audio = resolve_storage_key(row["audio_storage_key"])
                if audio.exists(): archive.write(audio, f"{index:04d}-{audio.name}")
        with session() as conn:
            conn.execute("INSERT INTO vf_exports (id, project_id, export_type, storage_key, file_name, status, task_id, format) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (uuid.uuid4().hex, project_id, "sentence_zip", key, path.name, "succeeded", task_id, "zip"))
        update_task(task_id, "succeeded", 1, output={"storage_key": key})
    except Exception as exc:
        update_task(task_id, "failed", 1, error_message=str(exc)); raise


def analyze_project(project_id: str):
    with session() as conn:
        rows = conn.execute("SELECT id, text, edited_text FROM vf_sentences WHERE project_id = ? ORDER BY order_index", (project_id,)).fetchall()
    source = "\n".join(f"{index + 1}. {(row['edited_text'] or row['text'])}" for index, row in enumerate(rows))
    if not source:
        raise ValueError("项目没有可分析文本")
    if len(source) > 100000:
        raise ValueError("项目文本超过分析上限")
    prompt = "分析以下配音文本，返回 JSON，包含 summary 字符串和 characters 数组。characters 每项包含 name、character_type、note。\n" + source
    response = LLMClient().chat("voiceforge_script_analysis", prompt, response_json=True)
    return response


def synthesize_voice_emotion(voice_id: str, emotion: str, text: str, instruct: str, interface_id: str, task_id: str):
    output_path = storage_root() / "temp" / f"{task_id}-emotion.wav"
    update_task(task_id, "running", 0.1)
    try:
        with session() as conn:
            task = conn.execute("SELECT status FROM vf_tasks WHERE id = ?", (task_id,)).fetchone()
            voice = conn.execute("SELECT * FROM vf_voices WHERE id = ?", (voice_id,)).fetchone()
        if not task or task["status"] == "cancelled" or not voice:
            return
        data = dict(voice)
        params = json.loads(data.get("params_json") or "{}")
        reference_key = data.get("preview_storage_key") or data.get("sample_storage_key") or data.get("reference_storage_key")
        reference_path = resolve_storage_key(reference_key) if reference_key else None
        if not reference_path or not reference_path.exists():
            raise ValueError("情绪片段需要该音色的默认试听片段作为可控克隆参考音频")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        engine = get_tts_engine(interface_id)
        design = params.get("voice_design") or data.get("design_text") or ""
        controllable = params.get("controllable_clone") or ""
        if data.get("mode") == "voice_design":
            design = f"{design}；情绪：{instruct}".strip("；")
        elif data.get("mode") == "controllable_clone":
            controllable = f"{controllable}；情绪：{instruct}".strip("；")
        succeeded = engine.synthesize(text, str(output_path), ref_audio=str(reference_path) if reference_path else None, mode="controllable_clone", voice=data.get("voice_id"), voice_design=design or None, controllable_clone=f"{controllable}；{instruct}".strip("；") or instruct, ref_text=params.get("ref_text"))
        if not succeeded or not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError("TTS 接口未返回有效情绪音频")
        output_key = f"voices/emotion-previews/{task_id}.wav"
        final_path = resolve_storage_key(output_key)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(output_path), str(final_path))
        update_task(task_id, "succeeded", 1, output={"voice_id": voice_id, "emotion": emotion, "text": text, "instruct": instruct, "interface_id": interface_id, "storage_key": output_key, "duration": audio_duration(final_path)})
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        update_task(task_id, "failed", 1, error_message=str(exc))
        raise


def create_task(project_id: str, task_type: str, input_data: dict, idempotency_key: str = None, voice_id: str = None):
    task_id = uuid.uuid4().hex
    with session() as conn:
        if idempotency_key:
            existing = conn.execute("SELECT id FROM vf_tasks WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
            if existing:
                return existing["id"], False
        conn.execute(
            "INSERT INTO vf_tasks (id, project_id, voice_id, task_type, idempotency_key, input_json) VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, project_id, voice_id, task_type, idempotency_key, json.dumps(input_data, ensure_ascii=False)),
        )
    return task_id, True
