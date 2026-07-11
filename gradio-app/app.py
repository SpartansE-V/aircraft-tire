"""Gradio app: MASt3R 3D reconstruction + defect detection projected into 3D.

Upload photos of a tyre (or any object). The app:
  1. detects surface defects/cracks in each image (Roboflow YOLO),
  2. reconstructs a dense 3D model from the images (MASt3R, via the reconstructor API),
  3. projects the 2D detections onto the dense point map, highlighting defect
     regions in red, and shows the result (GLB) in a 3D viewer.
"""

from __future__ import annotations

import os

import gradio as gr

from pipeline.config import (
    DEFAULT_DETECTION_MODEL,
    DETECTION_MODELS,
    OPTIM_LEVELS,
    get_config,
)
from pipeline.reconstructor_client import ReconstructorClient, ReconstructorError
from pipeline.runner import run_pipeline

CONFIG = get_config()
DETECTION_CHOICES = [(m.label, k) for k, m in DETECTION_MODELS.items()]
DETECTION_TABLE_HEADERS = ["image", "class", "confidence", "x", "y", "width", "height"]

DESCRIPTION = """
# Aircraft Tyre — 3D Defect Mapping (MASt3R)

Upload photos of a tyre. The app detects cracks / quality defects in 2D,
reconstructs the object in 3D with **MASt3R** (learning-based — works on
low-texture, few-image, and hard scenes where classic SfM fails), and
**projects the detections onto the dense 3D model** — defects in red.

> A handful of overlapping photos (or a turntable sequence) is enough. Even 2
> views can produce a model.
"""


def _environment_banner() -> str:
    client = ReconstructorClient(CONFIG.reconstructor_api_url)
    if client.health():
        line = f"✅ MASt3R reconstructor reachable at {CONFIG.reconstructor_api_url}."
        try:
            info = client.runtime_info()
            dev = info.get("resolved_device") or info.get("configured_device")
            if info.get("available"):
                line += f" Device: **{dev}** (torch {info.get('torch_version')})."
            else:
                line += f" ⚠️ torch/model not ready: {info.get('error', 'unknown')}."
        except ReconstructorError:
            pass
    else:
        line = (
            f"⚠️ MASt3R reconstructor not reachable at {CONFIG.reconstructor_api_url} — "
            "start/deploy it before running."
        )
    key_line = (
        "✅ Roboflow API key detected from the environment."
        if CONFIG.has_roboflow_key
        else "ℹ️ No Roboflow API key in the environment — paste one below to enable detection."
    )
    return f"{line}\n\n{key_line}"


_OUTPUT_ORDER = ["status", "summary", "model3d", "download", "gallery", "table", "logs"]


def _empty_outputs() -> dict[str, object]:
    return {
        "status": gr.update(value="", visible=False),
        "summary": "",
        "model3d": None,
        "download": gr.update(value=None, visible=False),
        "gallery": [],
        "table": [],
        "logs": "",
    }


def _as_tuple(outputs: dict[str, object]) -> tuple[object, ...]:
    return tuple(outputs[key] for key in _OUTPUT_ORDER)


def _run(
    files: list[str] | None,
    model_key: str,
    image_size: str,
    min_conf_thr: float,
    optim_level: str,
    confidence: float,
    api_key: str,
    progress: gr.Progress = gr.Progress(),  # noqa: B008 - Gradio dependency-injects this
):
    file_paths = list(files or [])
    outputs = _empty_outputs()
    if not file_paths:
        outputs["status"] = gr.update(value="⚠️ Please upload at least two images.", visible=True)
        yield _as_tuple(outputs)
        return

    for snapshot in run_pipeline(
        file_paths,
        model_key=model_key,
        api_key=api_key,
        image_size=int(image_size),
        min_conf_thr=float(min_conf_thr),
        optim_level=optim_level,
        confidence_threshold=confidence,
    ):
        progress(snapshot.fraction, desc=snapshot.stage)
        if snapshot.error:
            outputs["status"] = gr.update(value=f"❌ {snapshot.error}", visible=True)
        else:
            outputs["status"] = gr.update(
                value=f"**{snapshot.stage}** — {int(snapshot.fraction * 100)}%", visible=True
            )
        outputs["logs"] = snapshot.logs
        if snapshot.annotated_images:
            outputs["gallery"] = snapshot.annotated_images
        if snapshot.detection_rows:
            outputs["table"] = snapshot.detection_rows
        if snapshot.model_path:
            outputs["model3d"] = snapshot.model_path
            outputs["download"] = gr.update(value=snapshot.model_path, visible=True)
        if snapshot.summary_md:
            outputs["summary"] = snapshot.summary_md
        yield _as_tuple(outputs)


def build_demo() -> gr.Blocks:
    with gr.Blocks(title="Tyre 3D Defect Mapping (MASt3R)") as demo:
        gr.Markdown(DESCRIPTION)
        gr.Markdown(_environment_banner())

        with gr.Row():
            with gr.Column(scale=1):
                files = gr.File(
                    label="Images (upload 2+ photos)",
                    file_count="multiple",
                    file_types=["image"],
                    type="filepath",
                )
                model_key = gr.Dropdown(
                    label="Detection model", choices=DETECTION_CHOICES, value=DEFAULT_DETECTION_MODEL
                )
                confidence = gr.Slider(
                    label="Detection confidence threshold", minimum=0.0, maximum=1.0, step=0.05, value=0.5
                )
                api_key = gr.Textbox(
                    label="Roboflow API key",
                    type="password",
                    placeholder="Uses the ROBOFLOW_API_KEY env var if left blank",
                )
                with gr.Accordion("Reconstruction options (MASt3R)", open=False):
                    image_size = gr.Radio(
                        label="Input size", choices=["512", "224"], value=str(CONFIG.default_image_size),
                        info="512 is higher quality; 224 is faster.",
                    )
                    min_conf_thr = gr.Slider(
                        label="Min confidence (point cloud)", minimum=0.0, maximum=10.0, step=0.1,
                        value=CONFIG.default_min_conf_thr,
                        info="Higher drops noisier points.",
                    )
                    optim_level = gr.Dropdown(
                        label="Optimization level", choices=OPTIM_LEVELS, value=CONFIG.default_optim_level,
                        info="refine+depth is best; coarse is fastest.",
                    )
                run_button = gr.Button("Run reconstruction + detection", variant="primary")

            with gr.Column(scale=2):
                status = gr.Markdown(visible=False)
                summary = gr.Markdown()
                model3d = gr.Model3D(
                    label="3D model with projected defects (red)", clear_color=[0.1, 0.1, 0.1, 1.0]
                )
                download = gr.File(label="Download 3D model (.glb)", visible=False)
                with gr.Tab("Detections (2D)"):
                    gallery = gr.Gallery(label="Annotated images", columns=3, height=360)
                    table = gr.Dataframe(headers=DETECTION_TABLE_HEADERS, label="Detections", wrap=True)
                with gr.Tab("Logs"):
                    logs = gr.Textbox(label="Pipeline logs", lines=18, max_lines=18, autoscroll=True)

        run_button.click(
            fn=_run,
            inputs=[files, model_key, image_size, min_conf_thr, optim_level, confidence, api_key],
            outputs=[status, summary, model3d, download, gallery, table, logs],
        )
    return demo


demo = build_demo()


if __name__ == "__main__":
    demo.queue().launch(
        server_name=os.getenv("GRADIO_SERVER_NAME", "0.0.0.0"),
        server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
        theme=gr.themes.Soft(),
    )
