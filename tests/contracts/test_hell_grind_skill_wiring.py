from tools.graphics.gemini_fal_image import GeminiFalImage
from tools.graphics.openai_image import OpenAIImage
from tools.graphics.seedream_image import SeedreamImage
from tools.video.comfyui_video import ComfyUIVideo
from tools.video.higgsfield_video import HiggsFieldVideo
from tools.video.seedance_ark import SeedanceArkVideo
from tools.video.seedance_replicate import SeedanceReplicate
from tools.video.seedance_video import SeedanceVideo
from tools.video.video_selector import VideoSelector


def test_seedance_family_reads_cinedance_and_acting():
    for cls in (SeedanceVideo, SeedanceReplicate, SeedanceArkVideo, HiggsFieldVideo):
        assert {"cinedance", "acting-system"} <= set(cls().agent_skills)


def test_selector_reads_local_and_narrative_skills():
    assert {"cinedance", "acting-system", "hyperflow-h3"} <= set(VideoSelector().agent_skills)


def test_comfyui_video_advertises_hyperflow():
    assert "hyperflow-h3" in ComfyUIVideo().agent_skills


def test_image_tools_read_lira():
    for cls in (SeedreamImage, OpenAIImage, GeminiFalImage):
        assert "lira-image-prompts" in cls().agent_skills
