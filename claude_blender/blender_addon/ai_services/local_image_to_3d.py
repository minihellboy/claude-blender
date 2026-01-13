# SPDX-License-Identifier: MIT
"""
Local Image-to-3D services.

Runs 3D reconstruction models locally using PyTorch/Hugging Face.
No external API calls.

Supported models:
    - TripoSR: Fast feed-forward image-to-3D (Stability AI)
    - InstantMesh: High quality multi-view reconstruction

Requirements:
    pip install torch torchvision torchaudio
    pip install transformers accelerate
    pip install trimesh pygltflib
    pip install rembg  # For background removal
"""

import os
import tempfile
import time
from typing import Any, Dict, Optional
from .base import BaseLocalService, ModelOutputMixin, AIServiceError, ModelNotFoundError


class LocalTripoSR(BaseLocalService, ModelOutputMixin):
    """
    Local TripoSR image-to-3D service.

    TripoSR is a fast feed-forward model for single-image 3D reconstruction.
    Runs entirely locally using PyTorch.

    Model: stabilityai/TripoSR (Hugging Face)
    """

    MODEL_ID = "stabilityai/TripoSR"

    def __init__(self, device: Optional[str] = None):
        super().__init__()
        self.device = device
        self._model = None
        self._processor = None

    @property
    def service_name(self) -> str:
        return "triposr_local"

    @property
    def required_packages(self) -> list:
        return ["torch", "transformers", "trimesh", "PIL"]

    def _get_device(self) -> str:
        """Determine best device to use."""
        if self.device:
            return self.device

        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
            elif torch.backends.mps.is_available():
                return "mps"
            else:
                return "cpu"
        except:
            return "cpu"

    def load_model(self) -> bool:
        """Load TripoSR model."""
        if self._model is not None:
            return True

        try:
            import torch
            from transformers import AutoModel, AutoProcessor

            device = self._get_device()
            print(f"[TripoSR] Loading model on {device}...")

            self._processor = AutoProcessor.from_pretrained(
                self.MODEL_ID,
                trust_remote_code=True
            )
            self._model = AutoModel.from_pretrained(
                self.MODEL_ID,
                trust_remote_code=True
            ).to(device)

            self._model_loaded = True
            print("[TripoSR] Model loaded successfully")
            return True

        except Exception as e:
            print(f"[TripoSR] Failed to load model: {e}")
            return False

    def _remove_background(self, image_path: str) -> str:
        """Remove background from image using rembg."""
        try:
            from rembg import remove
            from PIL import Image

            input_img = Image.open(image_path)
            output_img = remove(input_img)

            # Save to temp file
            output_path = os.path.join(
                self._temp_dir,
                f"nobg_{int(time.time())}.png"
            )
            output_img.save(output_path)
            return output_path

        except ImportError:
            print("[TripoSR] rembg not installed, skipping background removal")
            return image_path
        except Exception as e:
            print(f"[TripoSR] Background removal failed: {e}")
            return image_path

    def generate(
        self,
        image_path: str,
        remove_background: bool = True,
        foreground_ratio: float = 0.85,
        output_format: str = "glb",
        mc_resolution: int = 256
    ) -> Dict[str, Any]:
        """
        Generate a 3D model from an image.

        Args:
            image_path: Path to input image
            remove_background: Whether to remove background first
            foreground_ratio: Ratio of foreground to image (0-1)
            output_format: Output format (glb, obj, ply)
            mc_resolution: Marching cubes resolution

        Returns:
            Dict with model path
        """
        if not self.load_model():
            return {
                "success": False,
                "error": "Failed to load TripoSR model. Install: pip install torch transformers trimesh"
            }

        try:
            from PIL import Image
            import torch

            # Load and preprocess image
            if remove_background:
                image_path = self._remove_background(image_path)

            image = Image.open(image_path).convert("RGB")

            # Process image
            device = self._get_device()
            inputs = self._processor(images=image, return_tensors="pt").to(device)

            # Generate 3D
            with torch.no_grad():
                outputs = self._model(**inputs)

            # Extract mesh
            mesh = outputs.meshes[0]

            # Save mesh
            output_path = os.path.join(
                self._temp_dir,
                f"triposr_{int(time.time())}.{output_format}"
            )

            if output_format == "glb":
                mesh.export(output_path, file_type="glb")
            elif output_format == "obj":
                mesh.export(output_path, file_type="obj")
            elif output_format == "ply":
                mesh.export(output_path, file_type="ply")

            return {
                "success": True,
                "filepath": output_path,
                "source_image": image_path,
                "format": output_format
            }

        except Exception as e:
            return {"success": False, "error": str(e)}


class LocalInstantMesh(BaseLocalService, ModelOutputMixin):
    """
    Local InstantMesh image-to-3D service.

    InstantMesh generates multi-view images and reconstructs 3D.
    Higher quality than TripoSR but slower.

    Requires more VRAM (~8GB+).
    """

    MODEL_ID = "TencentARC/InstantMesh"

    def __init__(self, device: Optional[str] = None):
        super().__init__()
        self.device = device
        self._pipeline = None

    @property
    def service_name(self) -> str:
        return "instantmesh_local"

    @property
    def required_packages(self) -> list:
        return ["torch", "diffusers", "transformers", "trimesh"]

    def load_model(self) -> bool:
        """Load InstantMesh pipeline."""
        if self._pipeline is not None:
            return True

        try:
            # InstantMesh requires custom loading
            # This is a placeholder - actual implementation depends on the model release
            print("[InstantMesh] Model loading not yet implemented")
            print("[InstantMesh] Use TripoSR for now, or install InstantMesh manually")
            return False

        except Exception as e:
            print(f"[InstantMesh] Failed to load: {e}")
            return False

    def generate(self, image_path: str, **kwargs) -> Dict[str, Any]:
        """Generate 3D from image."""
        if not self.load_model():
            return {
                "success": False,
                "error": "InstantMesh not available. Use triposr_local instead."
            }

        # Placeholder
        return {"success": False, "error": "Not implemented"}


class Depth2MeshService(BaseLocalService, ModelOutputMixin):
    """
    Generate 3D mesh from depth estimation.

    Uses MiDaS or Depth Anything for depth estimation,
    then converts to mesh.

    Lighter weight than full 3D reconstruction.
    """

    def __init__(self, device: Optional[str] = None):
        super().__init__()
        self.device = device
        self._depth_model = None

    @property
    def service_name(self) -> str:
        return "depth2mesh"

    @property
    def required_packages(self) -> list:
        return ["torch", "transformers", "numpy", "PIL"]

    def _get_device(self) -> str:
        if self.device:
            return self.device
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
            elif torch.backends.mps.is_available():
                return "mps"
            return "cpu"
        except:
            return "cpu"

    def load_model(self) -> bool:
        """Load depth estimation model."""
        if self._depth_model is not None:
            return True

        try:
            from transformers import pipeline

            device = self._get_device()
            # Use Depth Anything - works well and is fast
            self._depth_model = pipeline(
                "depth-estimation",
                model="LiheYoung/depth-anything-small-hf",
                device=0 if device == "cuda" else -1
            )
            self._model_loaded = True
            return True

        except Exception as e:
            print(f"[Depth2Mesh] Failed to load model: {e}")
            return False

    def generate(
        self,
        image_path: str,
        depth_scale: float = 1.0,
        output_format: str = "obj"
    ) -> Dict[str, Any]:
        """
        Generate a 3D mesh from image depth.

        Args:
            image_path: Path to input image
            depth_scale: Scale factor for depth
            output_format: Output format (obj, ply)

        Returns:
            Dict with mesh path
        """
        if not self.load_model():
            return {
                "success": False,
                "error": "Failed to load depth model"
            }

        try:
            from PIL import Image
            import numpy as np

            # Get depth map
            image = Image.open(image_path)
            depth_result = self._depth_model(image)
            depth = np.array(depth_result["depth"])

            # Normalize depth
            depth = (depth - depth.min()) / (depth.max() - depth.min())
            depth = depth * depth_scale

            # Convert to mesh (simple grid mesh)
            h, w = depth.shape
            vertices = []
            faces = []

            # Create vertices
            for y in range(h):
                for x in range(w):
                    # Normalize x, y to [-1, 1]
                    vx = (x / w - 0.5) * 2
                    vy = (y / h - 0.5) * -2  # Flip Y
                    vz = depth[y, x]
                    vertices.append([vx, vy, vz])

            # Create faces (triangles)
            for y in range(h - 1):
                for x in range(w - 1):
                    i = y * w + x
                    # Two triangles per quad
                    faces.append([i, i + 1, i + w])
                    faces.append([i + 1, i + w + 1, i + w])

            # Save as OBJ
            output_path = os.path.join(
                self._temp_dir,
                f"depth_mesh_{int(time.time())}.{output_format}"
            )

            with open(output_path, "w") as f:
                for v in vertices:
                    f.write(f"v {v[0]} {v[1]} {v[2]}\n")
                for face in faces:
                    f.write(f"f {face[0]+1} {face[1]+1} {face[2]+1}\n")

            return {
                "success": True,
                "filepath": output_path,
                "source_image": image_path,
                "format": output_format
            }

        except Exception as e:
            return {"success": False, "error": str(e)}


# Factory function
def get_local_image_to_3d(
    provider: str = "triposr",
    device: Optional[str] = None
) -> BaseLocalService:
    """
    Get a local image-to-3D service.

    Args:
        provider: Service provider (triposr, instantmesh, depth2mesh)
        device: Device to use (cuda, mps, cpu)

    Returns:
        Service instance
    """
    providers = {
        "triposr": LocalTripoSR,
        "instantmesh": LocalInstantMesh,
        "depth2mesh": Depth2MeshService,
    }

    service_class = providers.get(provider.lower())
    if not service_class:
        raise ValueError(f"Unknown provider: {provider}")

    return service_class(device=device)
