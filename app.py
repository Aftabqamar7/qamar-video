import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import streamlit as st
import uuid
import requests
from google.oauth2 import service_account
from google.auth.transport.requests import AuthorizedSession
from google.cloud import storage
from groq import Groq

st.set_page_config(page_title="PromptVideo Studio", page_icon="🎬", layout="wide")

st.markdown("""
<style>
.stApp {background: radial-gradient(circle at 15% 10%, #20234d 0, #0b1020 48%, #080b14 100%); color:#f5f7ff;}
section[data-testid="stSidebar"] {background:#10182b;}
.hero {padding:1.5rem 1.8rem;border:1px solid #344064;border-radius:20px;background:linear-gradient(120deg,#25234e,#123448);margin-bottom:1.2rem;}
.hero h1 {font-size:2.35rem;margin:0;color:#fff}.hero p {color:#d5def5;margin:.5rem 0 0}
div.stButton>button, div.stDownloadButton>button {border-radius:12px;font-weight:700;min-height:3rem}
</style>
""", unsafe_allow_html=True)

st.markdown(
    '<div class="hero"><h1>🎬 PromptVideo Studio</h1>'
    '<p>Turn a text prompt into a multi-scene AI video and export an MP4.</p></div>',
    unsafe_allow_html=True,
)

st.warning(
    "Veo video generation in this workflow uses Google Cloud Gemini Enterprise Agent Platform "
    "(Vertex AI authentication), not a standard Google AI Studio Google Cloud service-account credentials. "
    "Groq is optional and only plans scenes."
)

with st.sidebar:
    st.header("🔐 Google Cloud credentials")
    project_id = st.text_input("Google Cloud Project ID")
    bucket_name = st.text_input(
        "Cloud Storage bucket name",
        help="Create a Google Cloud Storage bucket in your project. Enter its name only, without gs://."
    )
    service_account_json = st.text_area(
        "Service account JSON",
        height=150,
        placeholder='Paste the full JSON key for a Google Cloud service account',
        help="Create a service account with Vertex AI User and permission to write/read objects in your bucket."
    )
    st.divider()
    st.header("Groq (optional)")
    groq_key = st.text_input(
        "Groq API key", type="password",
        help="Used only to expand your idea into scene prompts."
    )
    st.caption("Credentials are used for this session only. Never commit them to GitHub.")

left, right = st.columns([1.45, 1])
with left:
    prompt = st.text_area(
        "Describe the video you want", height=175,
        placeholder="Example: A futuristic city at night, flying cars, neon lights, cinematic camera movement..."
    )
with right:
    duration = st.select_slider("Final video duration", options=[20, 24, 30], value=24)
    aspect = st.selectbox("Video orientation", ["Landscape (16:9)", "Portrait (9:16)"])
    export_quality = st.selectbox("Export resolution", ["1080p HD", "2K (upscaled to 1440p)"])
    veo_model = st.selectbox(
        "Veo model",
        ["veo-3.1-generate-001", "veo-3.1-fast-generate-001"]
    )

st.caption(
    "The app generates separate 8-second clips and combines them. "
    "20 seconds uses 3 clips trimmed to 20 seconds; 24 seconds uses 3 clips; "
    "30 seconds uses 4 clips trimmed to 30 seconds."
)

def create_scene_prompts(user_prompt: str, scene_count: int, groq_api_key: str):
    """Use Groq for storyboarding, or create simple scene prompts without Groq."""
    if not groq_api_key:
        return [
            f"{user_prompt}. Shot {i + 1} of {scene_count}: create a distinct cinematic "
            "camera shot that continues the same story. Keep the same characters, "
            "wardrobe, location, lighting, and visual style. No subtitles or watermark."
            for i in range(scene_count)
        ]

    client = Groq(api_key=groq_api_key)
    instructions = f"""
Create exactly {scene_count} connected cinematic scene prompts for this video idea:
{user_prompt}

Return ONLY valid JSON in this exact shape:
{{"scenes": ["scene 1 prompt", "scene 2 prompt"]}}

Each prompt is for a separate 8-second video clip. Keep character appearance,
wardrobe, environment, time of day, lighting, and visual style consistent.
Each scene should continue the same story with a distinct action/camera beat.
Describe visible action and camera movement. Do not request text, subtitles,
logos, or watermarks. Do not include markdown fences.
"""
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": instructions}],
        temperature=0.65,
    )
    raw = response.choices[0].message.content.strip()
    raw = raw.removeprefix("```json").removesuffix("```").strip()
    data = json.loads(raw)
    scenes = data.get("scenes", [])
    if len(scenes) != scene_count or not all(isinstance(x, str) and x.strip() for x in scenes):
        raise ValueError("Groq did not return the expected number of scene prompts.")
    return scenes

def get_ffmpeg():
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None

def build_google_credentials(service_account_text: str, project: str):
    """Create scoped Google Cloud credentials from the user's service-account JSON."""
    try:
        info = json.loads(service_account_text)
    except json.JSONDecodeError as exc:
        raise ValueError("The Service Account JSON is invalid. Paste the complete JSON key file.") from exc

    if info.get("type") != "service_account":
        raise ValueError("The JSON must be a Google Cloud service-account key, not a Google Cloud service-account credentials.")

    credentials = service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    return credentials


def generate_veo_clip(
    credentials,
    project_id: str,
    bucket_name: str,
    prompt_text: str,
    model_name: str,
    aspect_ratio: str,
    destination: Path,
    progress_callback,
):
    """
    Generate one 8-second Veo clip using the documented Vertex AI REST API.
    Veo writes its result to the user's Cloud Storage bucket; this app downloads it.
    """
    session = AuthorizedSession(credentials)
    location = "us-central1"
    output_prefix = f"promptvideo-studio/{uuid.uuid4().hex}/"
    output_gcs_uri = f"gs://{bucket_name}/{output_prefix}"

    endpoint = (
        f"https://{location}-aiplatform.googleapis.com/v1/"
        f"projects/{project_id}/locations/{location}/publishers/google/models/"
        f"{model_name}:predictLongRunning"
    )
    request_body = {
        "instances": [{"prompt": prompt_text}],
        "parameters": {
            "storageUri": output_gcs_uri,
            "sampleCount": 1,
            "aspectRatio": aspect_ratio,
            "durationSeconds": 8,
            "resolution": "1080p",
        },
    }

    response = session.post(endpoint, json=request_body, timeout=120)

    if response.status_code >= 400:
        raise RuntimeError(
            f"Google Veo request failed ({response.status_code}): {response.text[:1800]}"
        )

    operation_data = response.json()
    operation_name = operation_data.get("name")
    if not operation_name:
        raise RuntimeError(f"Google did not return an operation name: {operation_data}")

    poll_url = (
        f"https://{location}-aiplatform.googleapis.com/v1/"
        f"projects/{project_id}/locations/{location}/publishers/google/models/"
        f"{model_name}:fetchPredictOperation"
    )
    while True:
        time.sleep(15)
        poll_response = session.post(
            poll_url, json={"operationName": operation_name}, timeout=120
        )
        if poll_response.status_code >= 400:
            raise RuntimeError(
                f"Could not check Veo generation status ({poll_response.status_code}): "
                f"{poll_response.text[:1500]}"
            )
        operation_data = poll_response.json()
        progress_callback()
        if operation_data.get("done"):
            break

    if operation_data.get("error"):
        raise RuntimeError(f"Veo generation failed: {operation_data['error']}")

    result = operation_data.get("response") or {}
    video_uri = None

    # REST response shape documented by Google is response.videos[].gcsUri.
    videos = result.get("videos") or result.get("generatedVideos") or []
    if videos:
        first_video = videos[0]
        video_uri = first_video.get("gcsUri")
        if not video_uri and isinstance(first_video.get("video"), dict):
            video_uri = first_video["video"].get("uri")

    if not video_uri:
        raise RuntimeError(
            "Veo finished but did not return a video Cloud Storage URI. "
            f"Response: {json.dumps(result)[:1500]}"
        )

    if not video_uri.startswith("gs://"):
        raise RuntimeError(f"Unexpected Veo output URI: {video_uri}")

# Download the generated object with the same service-account credentials.
    storage_client = storage.Client(project=project_id, credentials=credentials)
    bucket_part, blob_name = video_uri[5:].split("/", 1)
    blob = storage_client.bucket(bucket_part).blob(blob_name)
    blob.download_to_filename(str(destination))

    if not destination.exists() or destination.stat().st_size == 0:
        raise RuntimeError("The generated video file was empty or could not be downloaded.")


def assemble_video(clip_paths, output_path, seconds, quality, portrait):
    ffmpeg = get_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("FFmpeg was not found. Check that imageio-ffmpeg is installed.")

    # Preserve portrait or landscape composition. 2K means 2560x1440 landscape
    # or 1440x2560 portrait, upscaled from the 1080p Veo source.
    if portrait:
        size = "1440:2560" if quality.startswith("2K") else "1080:1920"
    else:
        size = "2560:1440" if quality.startswith("2K") else "1920:1080"

    with tempfile.TemporaryDirectory() as temp_dir:
        list_path = Path(temp_dir) / "concat_list.txt"
        # FFmpeg concat demuxer requires escaped single quotes in file paths.
        lines = []
        for clip in clip_paths:
            escaped = str(Path(clip).resolve()).replace("'", r"'\''")
            lines.append(f"file '{escaped}'")
        list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        command = [
            ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
            "-t", str(seconds),
            "-vf", f"scale={size}:force_original_aspect_ratio=decrease,"
                   f"pad={size}:(ow-iw)/2:(oh-ih)/2,setsar=1",
            "-r", "24", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", str(output_path)
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError("FFmpeg export failed: " + result.stderr[-2000:])

if st.button("🚀 Generate my video", type="primary", use_container_width=True):
    if not prompt.strip():
        st.error("Please enter a video prompt first.")
    elif not project_id.strip() or not bucket_name.strip() or not service_account_json.strip():
        st.error(
            "Enter your Google Cloud Project ID, Cloud Storage bucket name, "
            "and service-account JSON. A standard Google AI Studio Gemini API key cannot authenticate this Veo workflow."
        )
    else:
        scene_count = 3 if duration in (20, 24) else 4
        progress = st.progress(0)
        status = st.empty()
        try:
            status.info("Preparing your scene prompts...")
            scenes = create_scene_prompts(prompt.strip(), scene_count, groq_key.strip())

            with st.expander("Review scene prompts", expanded=False):
                for index, scene in enumerate(scenes, start=1):
                    st.markdown(f"**Scene {index}**")
                    st.write(scene)

            credentials = build_google_credentials(service_account_json, project_id.strip())
            portrait = aspect.startswith("Portrait")
            aspect_ratio = "9:16" if portrait else "16:9"

            with tempfile.TemporaryDirectory() as working_dir:
                clips = []
                for index, scene in enumerate(scenes):
                    status.info(
                        f"Generating clip {index + 1} of {scene_count} with Veo. "
                        "This may take several minutes."
                    )
                    clip_path = Path(working_dir) / f"scene_{index + 1}.mp4"

                    def poll_progress():
                        progress.progress(min(0.78, (index + 0.2) / scene_count * 0.78))

                    generate_veo_clip(
                        credentials,
                        project_id.strip(),
                        bucket_name.strip(),
                        scene,
                        veo_model,
                        aspect_ratio,
                        clip_path,
                        poll_progress,
                    )
                    clips.append(str(clip_path))
                    progress.progress((index + 1) / scene_count * 0.78)

                status.info("Combining scenes and exporting your MP4...")
                final_path = Path(working_dir) / "prompt_video.mp4"
                assemble_video(clips, final_path, duration, export_quality, portrait)
                video_data = final_path.read_bytes()

progress.progress(1.0)
            status.success(f"Your {duration}-second video is ready!")
            st.video(video_data)
            st.download_button(
                "⬇️ Download your MP4",
                data=video_data,
                file_name=f"prompt_video_{duration}s.mp4",
                mime="video/mp4",
                use_container_width=True,
            )
            st.caption(
                f"{duration} seconds • {export_quality} • MP4 • 24 FPS"
            )
        except json.JSONDecodeError:
            st.error(
                "Groq returned invalid JSON. Try again, or leave the Groq key blank "
                "to use automatic scene prompts."
            )
        except Exception as error:
            st.error(f"Video generation failed: {error}")
            st.info(
                "Check that your Google Cloud service-account credentials has Veo access, the selected model is "
                "available to your account, and billing/quota are enabled."
            )

with st.expander("Important details before deployment"):
    st.markdown("""
- **Veo generates the video through Google Cloud Gemini Enterprise Agent Platform / Vertex AI.** This version uses a Google Cloud service-account JSON key, project ID, and Cloud Storage bucket. A standard Google AI Studio Google Cloud service-account credentials is not accepted by this Veo workflow.
- Enable the Vertex AI API for your Google Cloud project. Give the service account the Vertex AI User role and read/write access to the output Cloud Storage bucket.
- **Groq is optional.** It writes connected scene prompts but cannot create video pixels.
- The app joins independently generated clips. Character and action continuity may vary between clips.
- **1080p** is requested from Veo. **2K** is an upscale to 2560×1440 (landscape) or 1440×2560 (portrait), not native 2K generation.
- Video generation may incur API charges and take several minutes per clip.
- Streamlit Cloud has resource and execution limits. Long-running generations may time out; a production app may need a background worker and object storage.
- Never place API keys in source code or commit them to GitHub.
""")
