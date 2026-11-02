from app import config


def test_paths_and_constants():
    assert config.AUDIO_ROOT.name == "audio_sources"
    assert config.TRANSCRIPTS_ROOT.name == "transcripts"
    assert config.FRONTEND_DIST.parts[-2:] == ("frontend", "dist")
    assert config.PORT == 8756
    assert "base" in config.WHISPER_MODELS
