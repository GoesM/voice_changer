# Project constraints

- GitHub `GoesM/voice_changer` is the long-term source of truth for code, issues, CI and releases.
- Publish downloadable Windows builds through GitHub Releases; keep README links and user tutorials current.
- Windows 11 first; local AI male-to-female conversion. Runtime audio processing must work offline. Model downloads are allowed.
- Never label pitch-only DSP as AI voice conversion. Never silently fall back to unprocessed microphone audio.
- Virtual microphone configuration once per application is acceptable. Prioritize Tencent Meeting and VALORANT.
- Do not commit models, private recordings, credentials or third-party binary plugins. Respect separate component distribution terms.
- Record measured validation separately from untested target-app compatibility and product goals.

