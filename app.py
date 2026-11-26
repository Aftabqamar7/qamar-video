
import os
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import streamlit as st
import requests
import fal_client
from groq import Groq


# ==========================================
# PAGE CONFIGURATION
# ==========================================

st.set_page_config(
    page_title="PromptVideo Studio",
    page_icon="🎬",
    layout="wide"
)

st.markdown("""
<style>
.stApp {
    background: radial-gradient(
        circle at 15% 10%,
        #20234d 0,
        #0b1020 48%,
        #080b14 100%
    );
    color: #f5f7ff;
}

section[data-testid="stSidebar"] {
    background: #10182b;
}

.hero {
    padding: 1.5rem 1.8rem;
    border: 1px solid #344064;
    border-radius: 20px;
    background: linear-gradient(120deg,#25234e,#123448);
    margin-bottom: 1.2rem;
}

.hero h1 {
    font-size: 2.35rem;
    margin: 0;
    color: white;
}

.hero p {
    color: #d5def5;
    margin-top: .5rem;
}

div.stButton > button,
div.stDownloadButton > button {
    border-radius: 12px;
    font-weight: 700;
    min-height: 3rem;
}
</style>
""", unsafe_allow_html=True)


st.markdown("""
<div class="hero">
    <h1>🎬 PromptVideo Studio</h1>
    <p>Turn your text prompt into an AI-generated video.</p>
</div>
""", unsafe_allow_html=True)


# ==========================================
# SIDEBAR API SETTINGS
# ==========================================

with st.sidebar:

    st.header("🔐 API Settings")

    fal_key = st.text_input(
        "fal.ai API Key",
        type="password",
        help="Required for video generation."
    )

    st.caption(
        "Get your API key from "
        "https://fal.ai/dashboard/keys"
    )

    st.divider()

    st.header("🧠 Groq Settings")

    groq_key = st.text_input(
        "Groq API Key (Optional)",
        type="password",
        help="Used only for creating scene prompts."
    )

    st.caption(
        "You can leave the Groq key empty."
    )

    st.divider()

    st.info(
        "Google Cloud Project ID, Cloud Storage "
        "and Service Account JSON are not required."
    )


# ==========================================
# MAIN USER INTERFACE
# ==========================================

left, right = st.columns([1.4, 1])

with left:

    prompt = st.text_area(
        "Describe the video you want",
        height=180,
        placeholder=(
            "Example: A futuristic city at night, "
            "flying cars, neon lights, cinematic "
            "camera movement..."
        )
    )

with right:

    duration = st.select_slider(
        "Final video duration",
        options=[8, 16, 20, 24, 30],
        value=24
    )

    aspect = st.selectbox(
        "Video orientation",
        [
            "Landscape (16:9)",
            "Portrait (9:16)"
        ]
    )

    quality = st.selectbox(
        "Export resolution",
        [
            "1080p HD",
            "2K (upscaled to 1440p)"
        ]
    )

    model_choice = st.selectbox(
        "AI Video Model",
        [
            "Veo 3.1 Standard",
            "Veo 3.1 Fast"
        ]
    )


st.caption(
    "Veo generates clips of up to 8 seconds. "
    "Longer videos are created by combining multiple clips."
)


# ==========================================
# SCENE PROMPT GENERATOR
# ==========================================

def create_scene_prompts(
    user_prompt,
    scene_count,
    groq_api_key
):

    if not groq_api_key:

        return [
            (
                f"{user_prompt}. This is scene {i + 1} "
                f"of {scene_count} in one continuous film. "
                "Keep the same characters, clothing, "
                "location, lighting and visual style. "
                "Use cinematic camera movement. "
                "No subtitles, logos or watermark."
            )
            for i in range(scene_count)
        ]

    client = Groq(api_key=groq_api_key)

    instructions = f"""
Create exactly {scene_count} connected cinematic
video scene prompts for this idea:

{user_prompt}

Return ONLY valid JSON in this format:

{{
    "scenes": [
        "scene 1 prompt",
        "scene 2 prompt"
    ]
}}

Each scene is for one separate 8-second video clip.

Keep characters, clothing, environment, lighting
and visual style consistent.

Each scene should continue the same story.

Do not include markdown or explanations.
"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "user",
                "content": instructions
            }
        ],
        temperature=0.65
    )

    raw = response.choices[0].message.content.strip()

    raw = raw.replace("```json", "").replace("```", "").strip()

    data = json.loads(raw)

    scenes = data.get("scenes", [])

    if len(scenes) != scene_count:
        raise ValueError(
            "Groq did not return the correct number of scenes."
        )

    return scenes


# ==========================================
# FAL.AI VIDEO GENERATION
# ==========================================

def generate_video_clip(
    api_key,
    scene_prompt,
    model_id,
    aspect_ratio,
    destination
):

    # fal_client reads the key from FAL_KEY.
    os.environ["FAL_KEY"] = api_key

    arguments = {
        "prompt": scene_prompt,
        "aspect_ratio": aspect_ratio,
        "resolution": "1080p",
        "generate_audio": True
    }

    # Veo 3.1 generates clips up to 8 seconds.
    result = fal_client.subscribe(
        model_id,
        arguments=arguments,
        with_logs=True
    )

    video_info = result.get("video", {})

    video_url = video_info.get("url")

    if not video_url:
        raise RuntimeError(
            f"fal.ai did not return a video URL: {result}"
        )

    # Download generated video.
    response = requests.get(
        video_url,
        stream=True,
        timeout=180
    )

    response.raise_for_status()

    with open(destination, "wb") as file:

        for chunk in response.iter_content(
            chunk_size=1024 * 1024
        ):

            if chunk:
                file.write(chunk)

    if not os.path.exists(destination):
        raise RuntimeError(
            "Generated video could not be downloaded."
        )

    if os.path.getsize(destination) == 0:
        raise RuntimeError(
            "Generated video file is empty."
        )


# ==========================================
# FFMPEG DETECTION
# ==========================================

def get_ffmpeg():

    ffmpeg = shutil.which("ffmpeg")

    if ffmpeg:
        return ffmpeg

    try:

        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()

    except Exception:

        return None


# ==========================================
# VIDEO ASSEMBLY AND EXPORT
# ==========================================

def assemble_video(
    clip_paths,
    output_path,
    seconds,
    export_quality,
    portrait
):

    ffmpeg = get_ffmpeg()

    if not ffmpeg:

        raise RuntimeError(
            "FFmpeg was not found. "
            "Install imageio-ffmpeg."
        )

    # Output dimensions.
    if portrait:

        if export_quality.startswith("2K"):
            size = "1440:2560"
        else:
            size = "1080:1920"

    else:

        if export_quality.startswith("2K"):
            size = "2560:1440"
        else:
            size = "1920:1080"

    with tempfile.TemporaryDirectory() as temp_dir:

        list_path = Path(temp_dir) / "videos.txt"

        lines = []

        for clip in clip_paths:

            escaped = str(
                Path(clip).resolve()
            ).replace("'", r"'\''")

            lines.append(
                f"file '{escaped}'"
            )

        list_path.write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8"
        )

        command = [
            ffmpeg,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_path),

            "-t", str(seconds),

            "-vf",
            (
                f"scale={size}:"
                "force_original_aspect_ratio=decrease,"
                f"pad={size}:(ow-iw)/2:(oh-ih)/2,"
                "setsar=1"
            ),

            "-r", "24",

            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",

            "-pix_fmt", "yuv420p",

            "-c:a", "aac",
            "-b:a", "192k",

            "-movflags", "+faststart",

            str(output_path)
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:

            raise RuntimeError(
                "FFmpeg export failed: "
                + result.stderr[-2500:]
            )


# ==========================================
# GENERATE VIDEO BUTTON
# ==========================================

if st.button(
    "🚀 Generate My Video",
    type="primary",
    use_container_width=True
):

    if not prompt.strip():

        st.error(
            "Please enter your video prompt."
        )

    elif not fal_key.strip():

        st.error(
            "Please enter your fal.ai API key in the sidebar."
        )

    else:

        scene_count = (duration + 7) // 8

        progress = st.progress(0)

        status = st.empty()

        try:

            # Create scenes.
            status.info(
                "Preparing your video scenes..."
            )

            scenes = create_scene_prompts(
                prompt.strip(),
                scene_count,
                groq_key.strip()
            )

            # Show scenes.
            with st.expander(
                "Review Generated Scene Prompts"
            ):

                for index, scene in enumerate(
                    scenes,
                    start=1
                ):

                    st.markdown(
                        f"**Scene {index}**"
                    )

                    st.write(scene)

            portrait = aspect.startswith("Portrait")

            aspect_ratio = (
                "9:16" if portrait else "16:9"
            )

            if model_choice == "Veo 3.1 Standard":

                model_id = "fal-ai/veo3.1"

            else:

                model_id = "fal-ai/veo3.1/fast"

            # Temporary working directory.
            with tempfile.TemporaryDirectory() as working_dir:

                clips = []

                # Generate each clip.
                for index, scene in enumerate(scenes):

                    status.info(
                        f"Generating clip {index + 1} "
                        f"of {scene_count}..."
                    )

                    clip_path = (
                        Path(working_dir)
                        / f"scene_{index + 1}.mp4"
                    )

                    generate_video_clip(
                        fal_key.strip(),
                        scene,
                        model_id,
                        aspect_ratio,
                        str(clip_path)
                    )

                    clips.append(str(clip_path))

                    progress.progress(
                        (index + 1) / (scene_count + 1)
                    )

                # Assemble final video.
                status.info(
                    "Combining scenes and exporting MP4..."
                )

                final_path = (
                    Path(working_dir)
                    / "prompt_video.mp4"
                )

                assemble_video(
                    clips,
                    final_path,
                    duration,
                    quality,
                    portrait
                )

                video_data = final_path.read_bytes()

            # Show final result.
            progress.progress(1.0)

            status.success(
                "Your AI video is ready!"
            )

            st.video(video_data)

            st.download_button(
                "⬇️ Download Your Video",
                data=video_data,
                file_name=f"prompt_video_{duration}s.mp4",
                mime="video/mp4",
                use_container_width=True
            )

            st.success(
                f"Video exported successfully: "
                f"{duration} seconds | {quality}"
            )

        except json.JSONDecodeError:

            st.error(
                "Groq returned invalid JSON. "
                "Try again or leave the Groq key empty."
            )

        except Exception as error:

            st.error(
                f"Video generation failed: {error}"
            )


# ==========================================
# INFORMATION
# ==========================================

with st.expander("Application Information"):

    st.markdown("""
    ### Video Generation

    - fal.ai Veo 3.1 generates the actual video.
    - Standard and Fast models are available.
    - Groq is optional and creates scene prompts.
    - Longer videos are assembled from separate clips.

    ### Export

    - MP4 format.
    - 24 FPS output.
    - H.264 video encoding.
    - AAC audio encoding.
    - 1080p HD export.
    - 2K upscaled export.

    **Important:** 2K in this version is upscaled
    from 1080p generated clips. It is not native 2K.

    ### API Security

    - API keys are entered by the user.
    - Do not hardcode API keys in this file.
    - Never upload API keys to GitHub.
    """)

