"""Pipeline that fuses COLMAP 3D reconstruction with Roboflow defect detection.

The public entry point is :func:`pipeline.runner.run_pipeline`, which takes a set
of uploaded images and produces a colored point cloud where surface defects
detected in 2D are projected onto the reconstructed 3D geometry.
"""
