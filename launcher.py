import sys

if __name__ == "__main__":
    if "--self-test" in sys.argv:
        import numpy as np
        import pedalboard
        import sounddevice
        from voice_changer.beatrice import make_preset
        from voice_changer import setup, studio, rvc
        from pathlib import Path
        assert Path(setup.__file__).with_name("engine_worker.py").is_file()
        assert Path(setup.__file__).with_name("engine-requirements.txt").is_file()
        assert make_preset("test.toml").startswith(b"VST3")
        assert np.isfinite(pedalboard.Gain(0)(np.zeros(960, dtype="float32"), 48000)).all()
        if "--report" in sys.argv:
            from pathlib import Path
            Path(sys.argv[sys.argv.index("--report") + 1]).write_text("PASS: packaged imports and DSP smoke test", encoding="utf-8")
    else:
        from voice_changer.gui import main
        main()
