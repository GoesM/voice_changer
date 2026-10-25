# Third-party components

Voice Changer: Copyright (c) 2026 GoesM. GPL-3.0; see LICENSE. Corresponding source for each release is at the matching Git tag in https://github.com/GoesM/voice_changer .

## Bundled runtime

- Python 3.12: PSF license, with Tcl/Tk runtime.
- NumPy 2.2.6: BSD-3-Clause and bundled numerical-library notices.
- Pedalboard 0.9.19, Spotify AB: GPL-3.0, with bundled JUCE/VST-host dependencies described in its notices. https://github.com/spotify/pedalboard/tree/v0.9.19
- sounddevice 0.5.3: MIT; its Windows wheel includes PortAudio under the PortAudio license.
- CFFI / pycparser: MIT.
- PyInstaller is a build tool with a GPL exception for generated executables.

The bundle's `licenses/` directory contains collected license texts and installed versions. Requirements files pin runtime dependencies. Model files and third-party VST binaries are excluded from our release.

## Downloaded separately

Beatrice 2.0.0-rc.3 Windows VST3: https://prj-beatrice.com/ . We host the unmodified plugin through the standard VST3 interface, without calling or distributing the private inference library. Official package licenses remain with downloads.

Official model 1 (2.0.0-rc.0): https://prj-beatrice.com/2.0.0-rc.0-official-model-1-terms . Published terms prohibit redistribution of model files. The app downloads directly from the official server after the user accepts terms; target voices have separate use conditions. The two female presets use Tsukuyomi-chan voices. Read the official conditions before use. Other upstream example models in the plugin package are not exposed as product presets.

VB-CABLE: https://vb-audio.com/Cable/ . Users download and install the official driver. No driver is bundled or installed silently. Commercial bundling would require a separate distribution decision.

The preset adapter uses the published Beatrice serialization schema and standard VST3 preset format. No inference code or model weights are copied into this repository. Third-party model and plugin terms are not replaced by this project's GPL license.

## Optional local training environment (v0.2)

Applio 3.7.0 (MIT, AI Hispano), pinned commit a864a1dc5aca33386753c40c192feac53ca71682, is downloaded directly from https://github.com/IAHispano/Applio on explicit user action; its LICENSE and TERMS_OF_USE.md remain in the installed source directory. uv 0.9.5 (MIT/Apache-2.0) is downloaded from https://github.com/astral-sh/uv. Python, PyTorch/CUDA and other dependencies retain their respective licenses in the managed environment. These binaries and model weights are not included in the application archive. The optional environment downloads base weights from upstream Applio model sources; voice rights and model terms are separate from the application GPL license. No third-party voice preset is newly redistributed in v0.2.
