PromptVideo Studio
A Streamlit application that creates a 20–30 second MP4 from a text prompt by generating several short clips with Google Veo and joining them with FFmpeg.
API responsibilities
- Google Gemini API / Veo: generates the actual video clips.
- Groq API (optional): expands the idea into connected scene prompts. Groq is not a video-generation model.
Features
- 20, 24 or 30-second final video
- Landscape (16:9) or portrait (9:16)
- 1080p export
- 2K export by upscaling the 1080p source
- MP4 preview and download
- Each user enters their own API keys
Run locally
1. Install Python 3.10 or newer.
2. Open a terminal in this folder.
3. Install dependencies:
   pip install -r requirements.txt
4. Start Streamlit:
   streamlit run app.py
5. Enter a Gemini API key in the sidebar. Enter a Groq key if you want automatic scene planning.
Deploy on Streamlit Community Cloud
1. Create a GitHub repository.
2. Upload app.py, requirements.txt, and README.md.
3. In Streamlit Community Cloud, create an app and select this repository and app.py.
4. Deploy. Users enter their own API keys in the sidebar.
Important limitations
- Veo generates short clips. This app composes multiple clips to reach the requested duration.
- Independently generated clips may not have perfect character/action continuity.
- 2K is an upscale from 1080p, not native 2K capture.
- Veo model availability, pricing, quotas, billing requirements and supported regions depend on Google's current API access for your account.
- Streamlit Cloud may time out or run out of memory during lengthy video generation. For a production service, consider moving generation into a background worker and storing results in object storage.
- Never commit API keys to GitHub.
