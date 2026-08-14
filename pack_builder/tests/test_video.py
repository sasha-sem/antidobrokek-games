from pathlib import Path

from dobrokek_pack_builder.video import probe_video, validate_browser_video


def test_browser_fixture_is_valid_h264() -> None:
    fixture = Path(__file__).parents[2] / "backend" / "tests" / "fixtures" / "sample.mp4"
    probe = probe_video(fixture)
    validate_browser_video(
        probe,
        max_duration_seconds=60,
        max_size_bytes=50 * 1024 * 1024,
    )
    assert probe.video_codec == "h264"
    assert probe.pixel_format == "yuv420p"
    assert probe.audio_codec == "aac"
